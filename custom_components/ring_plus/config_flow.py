"""Einrichtung ohne Eingaben: nutzt die Anmeldung der HA-Ring-Integration. Optionen: PIN fürs Aufschließen."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import CODE_FORMAT, CONF_UNLOCK_CODE, DOMAIN, RING_DOMAIN

_SECRET = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


class RingPlusOptionsFlow(OptionsFlow):
    """PIN fürs Aufschließen setzen oder entfernen (leer = keine PIN)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            code = str(user_input.get(CONF_UNLOCK_CODE) or "").strip()
            if code and not re.match(CODE_FORMAT, code):
                errors[CONF_UNLOCK_CODE] = "invalid_code"
            else:
                return self.async_create_entry(data={CONF_UNLOCK_CODE: code} if code else {})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Optional(CONF_UNLOCK_CODE): _SECRET}),
            description_placeholders={"state": "PIN" if self.config_entry.options.get(CONF_UNLOCK_CODE) else "-"},
            errors=errors,
        )


class RingPlusConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> RingPlusOptionsFlow:
        return RingPlusOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not self.hass.config_entries.async_entries(RING_DOMAIN):
            return self.async_abort(reason="ring_missing")
        if user_input is not None:
            return self.async_create_entry(title="Ring Intercom Plus", data={})
        return self.async_show_form(step_id="user")
