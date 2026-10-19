"""Einrichtung über die Oberfläche."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ring_plus.const import DOMAIN


async def test_ring_missing(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "ring_missing"


async def test_create(hass: HomeAssistant, ring_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ring Intercom Plus"


async def test_options_pin(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    lock = "lock.front_door_turoffner"
    result = await hass.config_entries.options.async_init(setup.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"unlock_code": "12"})
    assert result["errors"] == {"unlock_code": "invalid_code"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"unlock_code": " 1234 "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup.options == {"unlock_code": "1234"}
    assert hass.states.get(lock).attributes["code_format"] == r"^\d{4,8}$"  # Eintrag wurde neu geladen

    # leer = PIN wieder weg
    result = await hass.config_entries.options.async_init(setup.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup.options == {}
    assert "code_format" not in hass.states.get(lock).attributes
