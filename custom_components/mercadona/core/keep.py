"""Buzón de voz vía Google Keep.

Un Google Home no puede mandar texto libre a un servidor propio: lo único que hace con
"Ok Google, añade papel higiénico a la lista de la compra" es escribirlo en una lista de
Google Keep. Así que Keep se usa como buzón, no como lista: este poller lee lo que haya,
lo mete en el carrito de Mercadona y **borra la entrada de Keep**. La lista de verdad
sigue siendo el carrito de la app.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

log = logging.getLogger(__name__)


class KeepInbox:
    def __init__(self, email: str, master_token: str, list_name: str,
                 max_batch: int = 15) -> None:
        self._email = email
        self._master_token = master_token
        self._list_name = list_name
        # Tope por sondeo. Una lista de Keep usada antes a mano puede tener cientos de
        # elementos acumulados; sin este freno, el primer arranque volcaría todo el
        # historial al carrito de una vez. Lo que sobre se procesa en sondeos siguientes.
        self._max_batch = max_batch
        self._keep: Any = None

    def _connect(self) -> None:
        import gkeepapi  # import perezoso: el servicio arranca aunque no haya voz configurada

        keep = gkeepapi.Keep()
        keep.authenticate(self._email, self._master_token)
        self._keep = keep
        log.info("conectado a Google Keep como %s", self._email)

    def _find_list(self):
        assert self._keep is not None
        target = self._list_name.strip().lower()
        for note in self._keep.all():
            if (note.title or "").strip().lower() == target and not note.trashed:
                return note
        return None

    def _drain_sync(self) -> list[str]:
        """Saca los ítems sin marcar de la lista y los borra. Corre en un hilo aparte."""
        if self._keep is None:
            self._connect()
        assert self._keep is not None
        self._keep.sync()
        note = self._find_list()
        if note is None:
            log.warning("no encuentro la lista de Keep '%s'", self._list_name)
            return []

        # Solo lo que está sin marcar. Lo tachado es historial de compras anteriores:
        # procesarlo metería en el carrito todo lo que se compró alguna vez.
        pending = [i for i in note.items if not i.checked and (i.text or "").strip()]
        if len(pending) > self._max_batch:
            log.warning("la lista tiene %d elementos sin marcar; proceso %d en este ciclo",
                        len(pending), self._max_batch)
            pending = pending[:self._max_batch]

        items: list[str] = []
        for item in pending:
            items.append((item.text or "").strip())
            # Se borra ya: si el alta en el carrito falla, queda registrado como
            # pendiente en el panel. Dejarlo en Keep provocaría duplicados.
            item.delete()
        if items:
            self._keep.sync()
        return items

    async def drain(self) -> list[str]:
        return await asyncio.to_thread(self._drain_sync)


async def poll_loop(inbox: KeepInbox, handler: Callable[[str], Awaitable[None]],
                    interval: int) -> None:
    """Sondea el buzón sin parar. Nunca debe morir: los fallos se reintentan."""
    fails = 0
    while True:
        try:
            for text in await inbox.drain():
                log.info("voz: %r", text)
                try:
                    await handler(text)
                except Exception:
                    log.exception("no se pudo procesar %r", text)
            fails = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            fails += 1
            log.warning("fallo sondeando Keep (%d): %s", fails, e)
            # Si Keep está caído o el token ha caducado, espaciamos los intentos.
            await asyncio.sleep(min(300, interval * 2 ** min(fails, 5)))
            continue
        await asyncio.sleep(interval)
