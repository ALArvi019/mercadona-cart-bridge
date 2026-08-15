"""Servicio puente: voz → carrito de Mercadona, y panel para la tablet de la cocina."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import settings
from .core.catalog import Catalog
from .core.client import FileSessionStore, MercadonaClient, SessionExpired
from .core.keep import KeepInbox, poll_loop
from .core.matching import (AMBIGUITY_GAP, CONFIDENT_SCORE, Match, Matcher,
                            normalize, parse_intent, parse_request)
from .notify import Notifier
from .storage import Storage

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("bridge")

STATIC_DIR = Path(__file__).parent / "static"
REGULARS_TTL = 900       # 15 min
HISTORY_TTL = 6 * 3600


class State:
    """Estado compartido: cachés de habituales e historial, y el aviso de sesión caída."""

    def __init__(self) -> None:
        self.client: MercadonaClient
        self.catalog: Catalog
        self.storage: Storage
        self.matcher: Matcher
        self.regulars: list[dict[str, Any]] = []
        self.regulars_at: float = 0.0
        self.history: list[dict[str, Any]] = []
        self.history_at: float = 0.0
        self.session_error: str = ""
        self.notifier: Notifier = Notifier("")

    async def get_regulars(self, force: bool = False) -> list[dict[str, Any]]:
        if force or not self.regulars or time.time() - self.regulars_at > REGULARS_TTL:
            try:
                self.regulars = await self.client.my_regulars()
                self.regulars_at = time.time()
            except SessionExpired as e:
                self.session_error = str(e)
                raise
            except Exception as e:
                log.warning("no se pudieron leer los habituales: %s", e)
        return self.regulars

    async def get_history(self, force: bool = False) -> list[dict[str, Any]]:
        """Productos de los últimos pedidos, para que el emparejador prefiera lo ya comprado."""
        if not force and self.history and time.time() - self.history_at < HISTORY_TTL:
            return self.history
        products: dict[str, dict[str, Any]] = {}
        try:
            for order in (await self.client.orders())[:5]:
                oid = order.get("id")
                if oid is None:
                    continue
                detail = await self.client.order_detail(oid)
                for line in detail.get("lines", []) or []:
                    p = line.get("product")
                    if p:
                        products[str(p["id"])] = p
                await asyncio.sleep(0.2)
            self.history = list(products.values())
            self.history_at = time.time()
        except Exception as e:
            log.warning("no se pudo leer el historial de pedidos: %s", e)
        return self.history


state = State()


def _product_info(match, quantity: float) -> dict[str, Any]:
    """Datos del producto para que el aviso pueda enseñar foto y precio."""
    price = (match.product.get("price_instructions") or {}).get("unit_price")
    return {
        "frase": "",
        "producto": match.name,
        "producto_id": match.product_id,
        "imagen": match.product.get("thumbnail") or "",
        "precio": f"{float(price):.2f} €".replace(".", ",") if price else "",
        "cantidad": f"{quantity:g}",
    }


async def handle_remove(text: str, request) -> None:
    """Saca del carrito lo que se ha pedido quitar.

    Se busca solo entre lo que ya está en el carrito: fuera de ahí, "quita la
    mantequilla" no significa nada.
    """
    try:
        cart = await state.client.get_cart()
    except Exception as e:
        state.storage.log(text, "failed", detail=f"no se pudo leer el carrito: {e}")
        log.exception("no se pudo leer el carrito para quitar %r", text)
        return

    lines = cart.get("lines", [])
    products = [l["product"] for l in lines]
    match, _alternatives = state.matcher.resolve_in_cart(products, text)

    if match is None:
        state.storage.log(text, "pending", quantity=request.quantity,
                          detail="no encontrado en el carrito")
        log.info("no encuentro %r en el carrito", request.query)
        await state.notifier.send(
            "no_encontrado",
            "No está en el carrito",
            f"Querías quitar «{request.query}», pero no lo encuentro en el carrito.",
            {"frase": request.query},
        )
        return

    current = next((float(l["quantity"]) for l in lines
                    if str(l["product"]["id"]) == match.product_id), 0.0)
    # "quita 1 mantequilla" resta una; "quita mantequilla" saca la línea entera.
    new_qty = max(0.0, current - request.quantity) if request.explicit_quantity else 0.0

    if settings.dry_run:
        state.storage.log(text, "dry_run", match.product, new_qty, "cart", match.score,
                          "quitaría del carrito")
        log.info("[dry-run] dejaría %s en %s", match.name, new_qty)
        return

    try:
        await state.client.set_quantity(match.product_id, new_qty)
    except Exception as e:
        state.storage.log(text, "failed", match.product, new_qty, "cart", match.score, str(e))
        log.exception("no se pudo quitar %s del carrito", match.name)
        return

    state.storage.log(text, "removed", match.product, new_qty, "cart", match.score,
                      f"de {current:g} a {new_qty:g}")
    log.info("quitado %s: de %g a %g", match.name, current, new_qty)


async def handle_phrase(text: str) -> None:
    """Resuelve una frase dictada y la aplica al carrito."""
    request = parse_intent(text)
    if request.intent == "remove":
        await handle_remove(text, request)
        return

    match, alternatives, qty = state.matcher.resolve(text)

    if match is None:
        state.storage.log(text, "pending", quantity=qty,
                          detail="no encontrado con confianza suficiente")
        log.info("sin coincidencia clara para %r; queda pendiente en el panel", text)
        await state.notifier.send(
            "no_encontrado",
            "No sé qué comprar",
            f"No encuentro nada parecido a «{request.query}». Está esperando en el panel.",
            {"frase": request.query},
        )
        return

    if settings.dry_run:
        state.storage.log(text, "dry_run", match.product, qty, match.source, match.score)
        log.info("[dry-run] añadiría %s x%s", match.name, qty)
        return

    try:
        await state.client.add_product(match.product_id, qty)
    except Exception as e:
        state.storage.log(text, "failed", match.product, qty, match.source, match.score, str(e))
        log.exception("no se pudo añadir %s al carrito", match.name)
        await state.notifier.send(
            "fallo",
            "No he podido añadirlo",
            f"«{request.query}» no ha entrado en el carrito: {e}",
            _product_info(match, qty) | {"frase": request.query},
        )
        return

    state.storage.log(text, "added", match.product, qty, match.source, match.score)
    log.info("añadido %s x%s (%s, %.2f)", match.name, qty, match.source, match.score)

    # Se ha añadido, pero puede que no sea lo que se pedía: avisar si la elección
    # fue reñida o poco convincente, para poder corregirla a tiempo.
    rival = alternatives[0] if alternatives else None
    close_call = rival is not None and (match.score - rival.score) < AMBIGUITY_GAP
    unsure = match.score < CONFIDENT_SCORE
    if close_call or unsure:
        reason = (f"había otro casi igual: {rival.name}" if close_call and rival
                  else "no estoy seguro de haber acertado")
        await state.notifier.send(
            "ambiguo",
            "¿Es esto lo que querías?",
            f"Por «{request.query}» he puesto {match.name}, pero {reason}.",
            _product_info(match, qty) | {"frase": request.query,
                                         "alternativa": rival.name if rival else ""},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.client = MercadonaClient(
        FileSessionStore(settings.session_file),
        bootstrap_refresh_token=settings.mercadona_refresh_token,
        postal_code=settings.mercadona_postal_code,
        warehouse=settings.mercadona_warehouse,
    )
    state.catalog = Catalog(settings.catalog_file, settings.catalog_refresh_hours)
    await state.catalog.async_load()
    state.storage = Storage(settings.db_file)
    state.notifier = Notifier(settings.ha_webhook_url)
    state.matcher = Matcher(
        state.catalog,
        lambda: state.regulars,
        lambda: state.history,
        state.storage.alias,
    )

    tasks: list[asyncio.Task] = []
    try:
        await state.client.ensure_token()
        profile = await state.client.profile()
        log.info("sesión de %s (%s), almacén %s", profile.get("name"),
                 profile.get("current_postal_code"), state.client.session.warehouse)
        await state.get_regulars(force=True)
        tasks.append(asyncio.create_task(_warmup()))
    except SessionExpired as e:
        state.session_error = str(e)
        log.error("sesión de Mercadona no válida: %s", e)
    except Exception as e:
        log.exception("arranque incompleto: %s", e)

    if settings.gkeep_email and settings.gkeep_master_token:
        inbox = KeepInbox(settings.gkeep_email, settings.gkeep_master_token,
                          settings.gkeep_list_name, settings.gkeep_max_batch)
        tasks.append(asyncio.create_task(
            poll_loop(inbox, handle_phrase, settings.gkeep_poll_seconds)))
        log.info("buzón de voz activo sobre la lista de Keep '%s'", settings.gkeep_list_name)
    else:
        log.warning("Google Keep sin configurar: el panel funciona, la voz no")

    yield

    for t in tasks:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
    await state.client.close()


async def _warmup() -> None:
    """Catálogo e historial en segundo plano: el panel no debe esperar por ellos."""
    try:
        await state.catalog.refresh_if_stale(state.client)
        await state.get_history(force=True)
    except Exception as e:
        log.warning("calentamiento incompleto: %s", e)
    while True:
        await asyncio.sleep(settings.catalog_refresh_hours * 3600)
        try:
            await state.catalog.refresh(state.client)
            await state.get_history(force=True)
        except Exception as e:
            log.warning("refresco periódico falló: %s", e)


app = FastAPI(title="Mercadona cart bridge", lifespan=lifespan)


async def auth(request: Request, token: str = Query(default="")) -> None:
    """Token compartido. Si no se define, el servicio queda abierto en la LAN."""
    if not settings.app_api_token:
        return
    header = request.headers.get("authorization", "")
    given = header[7:] if header.lower().startswith("bearer ") else token
    if given != settings.app_api_token:
        raise HTTPException(status_code=401, detail="token no válido")


# ------------------------------------------------------------------ modelos

class AddBody(BaseModel):
    product_id: str
    quantity: float = 1.0


class QuantityBody(BaseModel):
    product_id: str
    quantity: float


class VoiceBody(BaseModel):
    text: str


class ResolveBody(BaseModel):
    product_id: str
    remember: bool = True


# ------------------------------------------------------------------ rutas

def _slim(p: dict[str, Any]) -> dict[str, Any]:
    price = (p.get("price_instructions") or {})
    return {
        "id": str(p["id"]),
        "name": p.get("display_name", ""),
        "packaging": p.get("packaging") or "",
        "thumbnail": p.get("thumbnail") or "",
        "price": price.get("unit_price"),
        "unit": price.get("size_format") or "",
        "unavailable": p.get("status") == "unavailable" or not p.get("published", True),
    }


@app.get("/api/state", dependencies=[Depends(auth)])
async def get_state() -> dict[str, Any]:
    """Todo lo que el panel necesita en una sola llamada."""
    cart_lines: list[dict[str, Any]] = []
    cart_total = None
    error = state.session_error
    try:
        cart = await state.client.get_cart()
        cart_lines = [{**_slim(l["product"]), "quantity": l["quantity"]}
                      for l in cart.get("lines", [])]
        cart_total = (cart.get("summary") or {}).get("total")
    except SessionExpired as e:
        error = state.session_error = str(e)
    except Exception as e:
        error = f"no se pudo leer el carrito: {e}"

    regulars = []
    with contextlib.suppress(Exception):
        in_cart = {l["id"] for l in cart_lines}
        regulars = [{**_slim(p), "in_cart": str(p["id"]) in in_cart}
                    for p in await state.get_regulars()]

    return {
        "cart": cart_lines,
        "cart_total": cart_total,
        "regulars": regulars,
        "pending": state.storage.pending(),
        "recent": state.storage.recent(12),
        "error": error,
        "dry_run": settings.dry_run,
        "catalog_size": len(state.catalog.products),
    }


@app.post("/api/cart/add", dependencies=[Depends(auth)])
async def cart_add(body: AddBody) -> dict[str, Any]:
    cart = await state.client.add_product(body.product_id, body.quantity)
    return {"ok": True, "products_count": cart.get("products_count")}


@app.post("/api/cart/quantity", dependencies=[Depends(auth)])
async def cart_quantity(body: QuantityBody) -> dict[str, Any]:
    cart = await state.client.set_quantity(body.product_id, body.quantity)
    return {"ok": True, "products_count": cart.get("products_count")}


@app.delete("/api/cart/{product_id}", dependencies=[Depends(auth)])
async def cart_delete(product_id: str) -> dict[str, Any]:
    await state.client.remove_product(product_id)
    return {"ok": True}


@app.get("/api/search", dependencies=[Depends(auth)])
async def search(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Búsqueda para el panel, con el mismo criterio que usa la voz."""
    match, alternatives, _ = state.matcher.resolve(q)
    results: list[Match] = ([match] if match else []) + alternatives

    # Si el emparejador ha sido restrictivo, completamos con coincidencias literales
    # del catálogo para que el panel siempre ofrezca de dónde elegir.
    if len(results) < limit:
        seen = {m.product_id for m in results}
        needle = normalize(q)
        for p in state.catalog.products.values():
            if len(results) >= limit:
                break
            if str(p["id"]) in seen:
                continue
            if needle and needle in normalize(p.get("display_name", "")):
                results.append(Match(p, 0.0, "catalog"))
                seen.add(str(p["id"]))

    return [{**_slim(m.product), "score": round(m.score, 3), "source": m.source}
            for m in results[:limit]]


@app.post("/api/voice", dependencies=[Depends(auth)])
async def voice(body: VoiceBody) -> dict[str, Any]:
    """Entrada de texto libre equivalente a la voz. Útil para probar y para webhooks."""
    await handle_phrase(body.text)
    entry = state.storage.recent(1)
    return {"ok": True, "result": entry[0] if entry else None}


@app.post("/api/pending/{entry_id}/resolve", dependencies=[Depends(auth)])
async def resolve_pending(entry_id: int, body: ResolveBody) -> dict[str, Any]:
    """El panel elige el producto correcto para una frase que quedó pendiente."""
    entry = state.storage.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="entrada no encontrada")

    product = state.catalog.products.get(str(body.product_id)) or \
        next((p for p in state.regulars if str(p["id"]) == str(body.product_id)), None)
    if not product:
        raise HTTPException(status_code=404, detail="producto no encontrado")

    await state.client.add_product(str(body.product_id), entry.get("quantity") or 1.0)
    state.storage.resolve_pending(entry_id, "added", product, "resuelto desde el panel")
    if body.remember:
        # La próxima vez que alguien diga lo mismo, irá directo a este producto.
        phrase, _ = parse_request(entry["phrase"])
        state.storage.set_alias(phrase, str(body.product_id))
    return {"ok": True}


@app.delete("/api/pending/{entry_id}", dependencies=[Depends(auth)])
async def discard_pending(entry_id: int) -> dict[str, Any]:
    state.storage.resolve_pending(entry_id, "discarded", detail="descartado desde el panel")
    return {"ok": True}


@app.get("/api/aliases", dependencies=[Depends(auth)])
async def list_aliases() -> list[dict[str, Any]]:
    return state.storage.aliases()


@app.delete("/api/aliases/{phrase}", dependencies=[Depends(auth)])
async def delete_alias(phrase: str) -> dict[str, Any]:
    state.storage.delete_alias(phrase)
    return {"ok": True}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": not state.session_error,
        "session_error": state.session_error,
        "catalog_size": len(state.catalog.products) if hasattr(state, "catalog") else 0,
        "regulars": len(state.regulars),
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
