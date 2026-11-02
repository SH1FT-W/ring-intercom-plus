"""Setup without input (uses the login of the HA Ring integration). Options: PIN, schedule for auto-unlock."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import CODE_FORMAT, CONF_AUTO_UNLOCK_SCHEDULE, CONF_UNLOCK_CODE, DOMAIN, RING_DOMAIN

_SECRET = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


class RingPlusOptionsFlow(OptionsFlow):
    """Menu: PIN for the door opener, or the schedule for "Next ring opens". Each step keeps the other option."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["pin", "auto_unlock"])

    def _save(self, key: str, value: str) -> ConfigFlowResult:
        options = {k: v for k, v in self.config_entry.options.items() if k != key}
        if value:
            options[key] = value
        return self.async_create_entry(data=options)

    async def async_step_auto_unlock(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Schedule helper: while it is on, every ring opens the door. Empty = no schedule."""
        if user_input is not None:
            return self._save(CONF_AUTO_UNLOCK_SCHEDULE, str(user_input.get(CONF_AUTO_UNLOCK_SCHEDULE) or ""))
        current = self.config_entry.options.get(CONF_AUTO_UNLOCK_SCHEDULE)
        return self.async_show_form(
            step_id="auto_unlock",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_AUTO_UNLOCK_SCHEDULE, description={"suggested_value": current}
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="schedule"))
                }
            ),
        )

    async def async_step_pin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set or remove the PIN (empty = no PIN)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            code = str(user_input.get(CONF_UNLOCK_CODE) or "").strip()
            if code and not re.match(CODE_FORMAT, code):
                errors[CONF_UNLOCK_CODE] = "invalid_code"
            else:
                return self._save(CONF_UNLOCK_CODE, code)
        return self.async_show_form(
            step_id="pin",
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
