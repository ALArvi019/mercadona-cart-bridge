"""Catálogo local del almacén.

La app usa Algolia, pero sus credenciales rotan y hay que rascarlas del bundle. Como el
catálogo de un almacén son unos pocos miles de productos y cambia poco, sale más barato
y mucho más estable descargarlo entero una vez al día y buscar en local.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _flatten(node: dict[str, Any], out: dict[str, dict[str, Any]]) -> None:
    for p in node.get("products", []) or []:
        if p.get("published", True):
            out[str(p["id"])] = p
    for sub in node.get("categories", []) or []:
        _flatten(sub, out)


class Catalog:
    def __init__(self, path: Path, refresh_hours: int = 24) -> None:
        self._path = path
        self._refresh_s = refresh_hours * 3600
        self.products: dict[str, dict[str, Any]] = {}
        self.updated_at: float = 0.0
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        """Lee el catálogo cacheado. Va en un hilo aparte: leer disco bloquea."""
        def read() -> dict:
            if not self._path.exists():
                return {}
            return json.loads(self._path.read_text())

        try:
            d = await asyncio.to_thread(read)
        except Exception as e:  # un catálogo corrupto no debe tumbar el servicio
            log.warning("no se pudo leer el catálogo cacheado: %s", e)
            return
        if d:
            self.products = d.get("products", {})
            self.updated_at = d.get("updated_at", 0.0)
            log.info("catálogo cargado de disco: %d productos", len(self.products))

    @property
    def is_stale(self) -> bool:
        return not self.products or (time.time() - self.updated_at) > self._refresh_s

    async def refresh(self, client) -> int:
        """Descarga el catálogo entero recorriendo las categorías raíz."""
        async with self._lock:
            products: dict[str, dict[str, Any]] = {}
            roots = await client.categories()
            for root in roots:
                for sub in root.get("categories", []) or [root]:
                    try:
                        detail = await client.category(sub["id"])
                    except Exception as e:
                        log.warning("categoría %s falló: %s", sub.get("id"), e)
                        continue
                    _flatten(detail, products)
                    # La API es de terceros: vamos a ritmo humano para no molestar.
                    await asyncio.sleep(0.25)
            if products:
                self.products = products
                self.updated_at = time.time()
                payload = json.dumps(
                    {"updated_at": self.updated_at, "products": products}, ensure_ascii=False)
                await asyncio.to_thread(self._path.write_text, payload)
                log.info("catálogo actualizado: %d productos", len(products))
            return len(self.products)

    async def refresh_if_stale(self, client) -> None:
        if self.is_stale:
            await self.refresh(client)
