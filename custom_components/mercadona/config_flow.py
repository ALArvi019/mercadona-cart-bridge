"""Configuración desde la interfaz de Home Assistant.

Mercadona no permite iniciar sesión de forma automática: su login exige un token de
reCAPTCHA Enterprise que solo se genera en un navegador o en la app. Por eso aquí no
se piden usuario y contraseña, sino un *refresh token* que se extrae una vez. A partir
de ahí la integración lo renueva sola.

Cómo obtenerlo está explicado paso a paso en la propia pantalla y en
docs/obtener-token.md.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_GKEEP_EMAIL,
    CONF_GKEEP_LIST,
    CONF_GKEEP_TOKEN,
    CONF_MAX_BATCH,
    CONF_POLL_SECONDS,
    CONF_POSTAL_CODE,
    CONF_REFRESH_TOKEN,
    CONF_WAREHOUSE,
    DEFAULT_MAX_BATCH,
    DEFAULT_POLL_SECONDS,
    DOMAIN,
)
from .core.client import MercadonaClient, SessionExpired
from .storage import MemorySessionStore

_LOGGER = logging.getLogger(__name__)

TOKEN_FIELD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD, multiline=True))
SECRET_FIELD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _validate_mercadona(refresh_token: str) -> dict[str, Any]:
    """Comprueba el token contra Mercadona y devuelve los datos de la cuenta."""
    client = MercadonaClient(MemorySessionStore(), bootstrap_refresh_token=refresh_token.strip())
    try:
        await client.ensure_token()
        profile = await client.profile()
        return {
            "name": profile.get("name") or "",
            "email": profile.get("email") or "",
            CONF_POSTAL_CODE: profile.get("current_postal_code") or "",
            # El almacén no viene en el perfil; se deduce del código postal más tarde.
            CONF_WAREHOUSE: client.session.warehouse,
            CONF_REFRESH_TOKEN: client.session.refresh_token,
            "customer_id": client.session.customer_id,
        }
    finally:
        await client.close()


def _list_keep_notes(email: str, master_token: str) -> list[tuple[str, int]]:
    """Listas de Keep de esa cuenta, con cuántos elementos sin marcar tiene cada una.

    Corre en un hilo aparte: gkeepapi es síncrona.
    """
    import gkeepapi

    keep = gkeepapi.Keep()
    keep.authenticate(email, master_token)
    keep.sync()
    notes: list[tuple[str, int]] = []
    for note in keep.all():
        if note.trashed or getattr(note, "items", None) is None:
            continue
        title = (note.title or "").strip()
        if not title:
            continue
        pending = sum(1 for i in note.items if not i.checked and (i.text or "").strip())
        notes.append((title, pending))
    return notes


# Como llama Google a la lista de la compra segun idioma y version. Sirven para
# premarcar las candidatas, no para filtrar: se ofrecen todas las listas de la cuenta.
SUGGESTED_LIST_NAMES = {
    "lista de la compra",
    "mi lista de la compra",
    "shopping list",
    "my shopping list",
}


class MercadonaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Alta de la integración."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._keep_notes: list[tuple[str, int]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Primer paso: el token de Mercadona."""
        errors: dict[str, str] = {}

        if user_input is not None:
            token = (user_input.get(CONF_REFRESH_TOKEN) or "").strip()
            try:
                account = await _validate_mercadona(token)
            except SessionExpired:
                errors["base"] = "token_rechazado"
            except Exception as err:  # red, API caída, respuesta rara...
                _LOGGER.debug("fallo validando el token: %s", err)
                errors["base"] = "sin_conexion"
            else:
                await self.async_set_unique_id(account["customer_id"])
                self._abort_if_unique_id_configured()
                self._data.update(
                    {
                        CONF_REFRESH_TOKEN: account[CONF_REFRESH_TOKEN],
                        CONF_POSTAL_CODE: user_input.get(CONF_POSTAL_CODE)
                        or account[CONF_POSTAL_CODE],
                        CONF_WAREHOUSE: (user_input.get(CONF_WAREHOUSE) or "").strip(),
                        "account_name": account["name"],
                    }
                )
                return await self.async_step_keep()

        schema = vol.Schema(
            {
                vol.Required(CONF_REFRESH_TOKEN): TOKEN_FIELD,
                vol.Optional(CONF_WAREHOUSE, default=""): str,
                vol.Optional(CONF_POSTAL_CODE, default=""): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_keep(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Segundo paso, opcional: el buzón de voz de Google Keep."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = (user_input.get(CONF_GKEEP_EMAIL) or "").strip()
            token = (user_input.get(CONF_GKEEP_TOKEN) or "").strip()

            if not email and not token:
                # Sin voz: el panel y las entidades funcionan igual.
                return self._create_entry()

            try:
                self._keep_notes = await self.hass.async_add_executor_job(
                    _list_keep_notes, email, token
                )
            except Exception as err:
                _LOGGER.debug("fallo validando Google Keep: %s", err)
                errors["base"] = "keep_rechazado"
            else:
                self._data[CONF_GKEEP_EMAIL] = email
                self._data[CONF_GKEEP_TOKEN] = token
                if not self._keep_notes:
                    errors["base"] = "keep_sin_listas"
                else:
                    return await self.async_step_keep_list()

        schema = vol.Schema(
            {
                vol.Optional(CONF_GKEEP_EMAIL, default=""): str,
                vol.Optional(CONF_GKEEP_TOKEN, default=""): SECRET_FIELD,
            }
        )
        return self.async_show_form(step_id="keep", data_schema=schema, errors=errors)

    async def async_step_keep_list(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Elegir qué listas de Keep rellena el Asistente.

        Se pueden marcar varias, y conviene. Google no deja elegir dónde escribe: la
        misma frase puede acabar en "Lista de la compra" o en "Mi lista de la compra"
        segun el idioma del altavoz o la cuenta. Vigilando todas las candidatas, la
        compra aparece se llame como se llame la lista de ese dia.

        Se muestran con el número de elementos pendientes porque es fácil tener varias
        con nombres parecidos, y apuntar a la equivocada volcaría cosas al carrito.
        """
        if user_input is not None:
            self._data[CONF_GKEEP_LIST] = user_input[CONF_GKEEP_LIST]
            return self._create_entry()

        options = [
            {
                "value": title,
                "label": f"{title} ({pending} sin marcar)" if pending else title,
            }
            for title, pending in self._keep_notes
        ]
        # Vienen premarcadas las que se llaman como suele llamarlas Google, que es lo
        # que acierta en la mayoría de casas.
        sugeridas = [
            title for title, _pending in self._keep_notes
            if title.strip().lower() in SUGGESTED_LIST_NAMES
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_GKEEP_LIST, default=sugeridas): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.LIST,
                        multiple=True,
                    )
                )
            }
        )
        return self.async_show_form(step_id="keep_list", data_schema=schema)

    def _create_entry(self) -> ConfigFlowResult:
        name = self._data.pop("account_name", "") or "Mercadona"

        if self.source == config_entries.SOURCE_RECONFIGURE:
            # Reconfigurar conserva lo que ya había y pisa solo lo que se ha tocado.
            entry = self._get_reconfigure_entry()
            return self.async_update_reload_and_abort(
                entry, data={**entry.data, **self._data}
            )

        return self.async_create_entry(title=f"Mercadona ({name})", data=self._data)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cambiar la configuración sin volver a dar de alta la integración.

        Sirve sobre todo para activar la voz después, que es lo normal: primero se
        prueba el carrito y el panel, y cuando convence se conecta Google Keep.
        """
        entry = self._get_reconfigure_entry()
        self._data = {}
        # Se mantiene la sesión de Mercadona tal cual está.
        self._data[CONF_REFRESH_TOKEN] = entry.data.get(CONF_REFRESH_TOKEN, "")
        return await self.async_step_keep(user_input)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Cuando el token deja de valer, Home Assistant pide uno nuevo."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            token = (user_input.get(CONF_REFRESH_TOKEN) or "").strip()
            try:
                account = await _validate_mercadona(token)
            except SessionExpired:
                errors["base"] = "token_rechazado"
            except Exception:
                errors["base"] = "sin_conexion"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_REFRESH_TOKEN: account[CONF_REFRESH_TOKEN]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_REFRESH_TOKEN): TOKEN_FIELD}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return MercadonaOptionsFlow()


class MercadonaOptionsFlow(OptionsFlow):
    """Ajustes que se pueden cambiar sin volver a dar de alta la integración."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_POLL_SECONDS,
                    default=current.get(CONF_POLL_SECONDS, DEFAULT_POLL_SECONDS),
                ): vol.All(int, vol.Range(min=5, max=300)),
                vol.Optional(
                    CONF_MAX_BATCH, default=current.get(CONF_MAX_BATCH, DEFAULT_MAX_BATCH)
                ): vol.All(int, vol.Range(min=1, max=100)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
