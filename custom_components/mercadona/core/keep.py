"""Buzón de voz vía Google Keep.

Un Google Home no puede mandar texto libre a un servidor propio: lo único que hace con
"Ok Google, añade papel higiénico a la lista de la compra" es escribirlo en una lista de
Google Keep. Así que Keep se usa como buzón, no como lista: este poller lee lo que haya,
lo mete en el carrito de Mercadona y **borra la entrada de Keep**. La lista de verdad
sigue siendo el carrito de la app.

Se vigila más de una lista a propósito. Google no siempre escribe en la misma: según el
idioma del altavoz, la cuenta o el humor de turno, la frase acaba en "Lista de la compra"
o en "Mi lista de la compra", y el usuario no tiene forma de elegirlo. Cuando la lista
vigilada no es la que Google usa, no falla nada, simplemente no aparece nunca nada, que
es el peor modo de fallo posible. Vigilando todas las candidatas eso deja de pasar.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


def normalize_list_names(value: Any) -> list[str]:
    """Acepta lo que haya guardado la configuración y devuelve siempre una lista.

    Las versiones anteriores a la 0.2.0 guardaban un solo nombre como cadena, y hay
    entradas de configuración por ahí que siguen así. Se admiten los dos formatos para
    que actualizar no obligue a reconfigurar nada.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    return [name.strip() for name in value if name and name.strip()]


class KeepInbox:
    def __init__(self, email: str, master_token: str,
                 list_names: str | list[str],
                 max_batch: int = 15) -> None:
        self._email = email
        self._master_token = master_token
        self._list_names = normalize_list_names(list_names)
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

    def _find_lists(self) -> list:
        assert self._keep is not None
        targets = {name.lower() for name in self._list_names}
        return [
            note for note in self._keep.all()
            if not note.trashed and (note.title or "").strip().lower() in targets
        ]

    def _available_titles(self) -> list[str]:
        """Listas de la cuenta, para poder decir en el aviso qué nombres si existen."""
        assert self._keep is not None
        return sorted(
            (note.title or "").strip()
            for note in self._keep.all()
            if not note.trashed and getattr(note, "items", None) is not None
            and (note.title or "").strip()
        )

    def _drain_sync(self) -> list[str]:
        """Saca los ítems sin marcar de la lista y los borra. Corre en un hilo aparte."""
        if self._keep is None:
            self._connect()
        assert self._keep is not None
        self._keep.sync()
        notes = self._find_lists()
        if not notes:
            # Se dice qué listas hay de verdad, porque el fallo tipico es que Google
            # escriba en una lista con un nombre parecido pero no igual.
            log.warning(
                "no encuentro ninguna de las listas de Keep %s. En esta cuenta hay: %s",
                self._list_names, self._available_titles() or "ninguna",
            )
            return []

        # Solo lo que está sin marcar. Lo tachado es historial de compras anteriores:
        # procesarlo metería en el carrito todo lo que se compró alguna vez.
        pending = [
            (note, item)
            for note in notes
            for item in note.items
            if not item.checked and (item.text or "").strip()
        ]
        if len(pending) > self._max_batch:
            log.warning("hay %d elementos sin marcar; proceso %d en este ciclo",
                        len(pending), self._max_batch)
            pending = pending[:self._max_batch]

        items: list[str] = []
        for _note, item in pending:
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
