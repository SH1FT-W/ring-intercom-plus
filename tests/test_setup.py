"""Einrichtung: Entitäten hängen am Ring-Gerät, Startwerte aus der Cloud."""

from __future__ import annotations

from types import SimpleNamespace

from conftest import DING_ENTITY
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from common import DEVICE_API_ID, MAC, FakeRing, fake_intercom
from custom_components.ring_plus.const import DOMAIN

EXPECTED = {
    "switch.front_door_nachstes_klingeln_offnet": "off",
    "switch.front_door_ring_to_open": "off",
    "number.front_door_offnungsdauer": "3",
    "binary_sensor.front_door_anruf_aktiv": "off",
    "binary_sensor.front_door_klingel": "off",
    "lock.front_door_turoffner": "locked",
    "button.front_door_neustart": "unknown",
    "sensor.front_door_hardware_revision": "RS-2",
    "sensor.front_door_anlagentyp": "analog",
    "sensor.front_door_entsperr_modus": "0",
}


async def test_entities(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    for entity_id, state in EXPECTED.items():
        assert hass.states.get(entity_id) is not None, entity_id
        assert hass.states.get(entity_id).state == state, entity_id


async def test_attached_to_ring_device(
    hass: HomeAssistant, ring_entry: MockConfigEntry, setup: MockConfigEntry
) -> None:
    device = dr.async_get(hass).async_get_device_by_identifier(("ring", MAC), ring_entry.entry_id)
    assert device is not None
    ours = [e for e in er.async_entries_for_device(er.async_get(hass), device.id) if e.platform == DOMAIN]
    assert len(ours) == len(EXPECTED)
    assert len(dr.async_get(hass).devices) == 1  # kein zweites Gerät


async def test_waits_for_ring(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_no_analog_no_duration(hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry) -> None:
    ring.settings["config"] = '{"digital":{"audio_amp":1}}'
    ring.settings["intercom_type"] = "digital"
    hass.config.language = "de"
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("number.front_door_offnungsdauer") is None
    assert hass.states.get("switch.front_door_nachstes_klingeln_offnet") is not None


async def test_ring_structure_changed(hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry) -> None:
    """Ring ohne devices.all_devices (Aufbau geändert): sauber „wird erneut versucht“ statt Traceback."""
    ring_entry.runtime_data = SimpleNamespace(api=ring)
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize("broken", ["missing_id", "error"])
async def test_profile_without_id(
    hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry, broken: str
) -> None:
    """Ohne Benutzer-ID gibt es kein „Nächstes Klingeln öffnet“, der Rest läuft."""
    if broken == "missing_id":
        ring.profile = {"name": "ohne id"}
    else:
        ring.profile_error = True
    hass.config.language = "de"
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.front_door_nachstes_klingeln_offnet") is None
    assert hass.states.get("lock.front_door_turoffner").state == "locked"


async def test_ring_unloaded_at_runtime(
    hass: HomeAssistant, ring_entry: MockConfigEntry, setup: MockConfigEntry
) -> None:
    ring_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    del ring_entry.runtime_data
    await setup.runtime_data.intercoms[0].async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("switch.front_door_ring_to_open").state == "unavailable"


async def test_ring_reload_reloads_ring_plus(
    hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry, setup: MockConfigEntry
) -> None:
    """Lädt die Ring-Integration neu, lädt Ring Intercom Plus hinterher (sonst bliebe das alte Ring-Objekt kaputt)."""

    def profile_calls() -> int:
        return sum(1 for call in ring.calls if call[1] == "/clients_api/profile")

    before = profile_calls()
    # Datenänderung (Ring speichert Tokens) löst nichts aus
    hass.config_entries.async_update_entry(ring_entry, data={"token": "neu"})
    await hass.async_block_till_done()
    assert profile_calls() == before

    ring_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    await hass.async_block_till_done()
    assert profile_calls() == before
    ring_entry.runtime_data = SimpleNamespace(api=ring, devices=SimpleNamespace(all_devices=[fake_intercom()]))
    ring_entry.mock_state(hass, ConfigEntryState.LOADED)
    await hass.async_block_till_done()
    assert setup.state is ConfigEntryState.LOADED
    assert profile_calls() == before + 1  # einmal neu eingerichtet
    assert hass.states.get("switch.front_door_ring_to_open").state == "off"


async def test_ring_removed(hass: HomeAssistant, ring_entry: MockConfigEntry, setup: MockConfigEntry) -> None:
    await hass.config_entries.async_remove(ring_entry.entry_id)
    await hass.async_block_till_done()
    assert setup.state is ConfigEntryState.SETUP_RETRY


async def test_ding_entity_renamed(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    """Wird das Klingel-Ereignis von ring umbenannt, hört Ring Intercom Plus auf die neue ID."""
    new_id = "event.haustuer_klingel"
    er.async_get(hass).async_update_entity(DING_ENTITY, new_entity_id=new_id)
    await hass.async_block_till_done()
    hass.states.async_remove(DING_ENTITY)
    hass.states.async_set(new_id, "2026-10-12T10:05:00.000+00:00", {"event_type": "ding"})
    hass.states.async_set(new_id, "2026-10-12T10:06:00.000+00:00", {"event_type": "ding"})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_klingel").state == "on"


async def test_ding_entity_appears_later(hass: HomeAssistant, ring_entry: MockConfigEntry) -> None:
    registry = er.async_get(hass)
    registry.async_remove(DING_ENTITY)
    hass.states.async_remove(DING_ENTITY)
    hass.config.language = "de"
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry.async_get_or_create(
        "event", "ring", f"{DEVICE_API_ID}-ding", suggested_object_id="main_entrance_klingeln", config_entry=ring_entry
    )
    await hass.async_block_till_done()
    hass.states.async_set(DING_ENTITY, "2026-10-12T10:05:00.000+00:00", {"event_type": "ding"})
    hass.states.async_set(DING_ENTITY, "2026-10-12T10:06:00.000+00:00", {"event_type": "ding"})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_klingel").state == "on"
