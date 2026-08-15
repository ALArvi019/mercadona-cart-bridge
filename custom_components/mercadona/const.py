"""Constantes de la integración."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "mercadona"

# --- claves de configuración ---
CONF_REFRESH_TOKEN = "refresh_token"
CONF_POSTAL_CODE = "postal_code"
CONF_WAREHOUSE = "warehouse"
CONF_GKEEP_EMAIL = "gkeep_email"
CONF_GKEEP_TOKEN = "gkeep_master_token"
CONF_GKEEP_LIST = "gkeep_list_name"
CONF_POLL_SECONDS = "poll_seconds"
CONF_MAX_BATCH = "max_batch"
CONF_NOTIFY_TARGETS = "notify_targets"
CONF_TTS_TARGET = "tts_target"

DEFAULT_LIST_NAME = "Lista de la compra"
DEFAULT_POLL_SECONDS = 15
DEFAULT_MAX_BATCH = 15

# El carrito se relee cada poco: los dos móviles de casa pueden tocarlo desde la app.
UPDATE_INTERVAL = timedelta(minutes=2)
# El catálogo del almacén cambia poco y son unos 4.300 productos.
CATALOG_INTERVAL = timedelta(hours=24)
# Los habituales los recalcula Mercadona a su ritmo.
REGULARS_INTERVAL = timedelta(minutes=15)

# Evento en el bus de Home Assistant cuando el emparejador duda o no encuentra algo.
# Se deja que una automatización decida qué hacer con él.
AMBIGUITY_EVENT = f"{DOMAIN}_aviso"

PANEL_URL = "mercadona-compra"
PANEL_TITLE = "Compra"
PANEL_ICON = "mdi:cart"

# La sesión se guarda aparte de la configuración porque el refresh token rota en
# cada renovación y no queremos reescribir el config entry constantemente.
STORAGE_KEY = f"{DOMAIN}.session"
STORAGE_VERSION = 1
