"""Avisos hacia Home Assistant.

El servicio no habla con la API de Home Assistant (haría falta un token de larga
duración): publica en un webhook, que HA expone sin autenticación dentro de la red
local. Así el aviso no obliga a guardar más credenciales en la Raspberry.

Un aviso nunca debe tumbar el flujo: si HA no responde, se registra y se sigue.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, webhook_url: str, timeout: float = 8.0) -> None:
        self._url = webhook_url
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    async def send(self, kind: str, title: str, message: str,
                   extra: dict[str, Any] | None = None) -> None:
        """kind: 'ambiguo' | 'no_encontrado' | 'fallo'."""
        if not self.enabled:
            return
        payload = {"tipo": kind, "titulo": title, "mensaje": message, **(extra or {})}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                r = await http.post(self._url, json=payload)
                if r.status_code >= 400:
                    log.warning("Home Assistant devolvió %s al avisar", r.status_code)
        except Exception as e:
            log.warning("no se pudo avisar a Home Assistant: %s", e)
