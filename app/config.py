"""Configuración del servicio, leída del entorno."""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Mercadona. El refresh token del entorno solo sirve para el primer arranque:
    # a partir de ahí manda el que se haya persistido en data/session.json, porque
    # Mercadona lo rota en cada renovación.
    mercadona_refresh_token: str = ""
    mercadona_postal_code: str = ""
    mercadona_warehouse: str = ""

    # Google Keep (buzón de voz)
    gkeep_email: str = ""
    gkeep_master_token: str = ""
    gkeep_list_name: str = "Lista de la compra"
    gkeep_poll_seconds: int = 15
    # Tope de elementos procesados por sondeo, por si la lista trae un atracón.
    gkeep_max_batch: int = 15

    # Aviso a Home Assistant cuando la elección es dudosa o falla algo.
    # Webhook de HA, que no necesita token: http://IP:8123/api/webhook/<id>
    ha_webhook_url: str = ""

    # Servicio
    app_api_token: str = ""
    app_port: int = 8099
    dry_run: bool = False

    # Cada cuántas horas se refresca el catálogo local del almacén
    catalog_refresh_hours: int = 24

    data_dir: Path = Field(default=Path("data"))

    @property
    def session_file(self) -> Path:
        return self.data_dir / "session.json"

    @property
    def catalog_file(self) -> Path:
        return self.data_dir / "catalog.json"

    @property
    def db_file(self) -> Path:
        return self.data_dir / "bridge.db"


settings = Settings()
settings.data_dir = Path(os.getenv("DATA_DIR", settings.data_dir))
settings.data_dir.mkdir(parents=True, exist_ok=True)
