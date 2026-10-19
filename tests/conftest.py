"""Fixtures: HA-Ring-Eintrag samt Gerät und Klingel-Ereignis vortäuschen, dann Ring Intercom Plus einrichten."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockModule, mock_integration

from common import DEVICE_API_ID, MAC, FakeRing, fake_intercom
from custom_components.ring_plus.const import DOMAIN

DING_ENTITY = "event.main_entrance_klingeln"
ACTIVITY_ENTITY = "sensor.main_entrance_letzte_aktivitat"
UNLOCK_ENTITY = "event.main_entrance_gegensprechanlage_entsperren"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


@pytest.fixture
def ring() -> FakeRing:
    return FakeRing()


async def _unload(hass: HomeAssistant, entry: object) -> bool:
    return True


@pytest.fixture
def ring_entry(hass: HomeAssistant, ring: FakeRing) -> MockConfigEntry:
    # Echte HA-Ring-Integration braucht ring_doorbell – hier nur eine Attrappe
    mock_integration(hass, MockModule("ring", async_unload_entry=_unload))
    entry = MockConfigEntry(domain="ring", title="Ring", data={})
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = SimpleNamespace(api=ring, devices=SimpleNamespace(all_devices=[fake_intercom()]))
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("ring", MAC)}, name="Main Entrance"
    )
    device = devices.async_update_device(device.id, name_by_user="Front Door")
    er.async_get(hass).async_get_or_create(
        "event",
        "ring",
        f"{DEVICE_API_ID}-ding",
        suggested_object_id="main_entrance_klingeln",
        config_entry=entry,
        device_id=device.id,
    )
    er.async_get(hass).async_get_or_create(
        "event",
        "ring",
        f"{DEVICE_API_ID}-intercom_unlock",
        suggested_object_id="main_entrance_gegensprechanlage_entsperren",
        config_entry=entry,
        device_id=device.id,
    )
    er.async_get(hass).async_get_or_create(
        "sensor",
        "ring",
        f"{DEVICE_API_ID}-last_activity",
        suggested_object_id="main_entrance_letzte_aktivitat",
        config_entry=entry,
        device_id=device.id,
    )
    hass.states.async_set(
        ACTIVITY_ENTITY, "2026-10-12T08:00:00+00:00", {"category": "ding", "created_at": "2026-10-12T08:00:00+00:00"}
    )
    hass.states.async_set(UNLOCK_ENTITY, "2026-10-12T09:00:00.000+00:00", {"event_type": "intercom_unlock"})
    hass.states.async_set(DING_ENTITY, "2026-10-12T10:00:00.000+00:00", {"event_type": "ding"})
    return entry


@pytest.fixture
async def setup(hass: HomeAssistant, ring_entry: MockConfigEntry) -> MockConfigEntry:
    hass.config.language = "de"
    entry = MockConfigEntry(domain=DOMAIN, title="Ring Intercom Plus", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
