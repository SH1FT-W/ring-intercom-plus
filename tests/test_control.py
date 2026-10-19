"""Befehle: Formate wie in der Ring-App."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json

from conftest import ACTIVITY_ENTITY, DING_ENTITY, UNLOCK_ENTITY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from common import DEVICE_API_ID, USER_ID, FakeRing
from custom_components.ring_plus.api import unlock_duration
from custom_components.ring_plus.const import DOMAIN

AUTO = "switch.front_door_nachstes_klingeln_offnet"


async def _call(hass: HomeAssistant, domain: str, service: str, entity_id: str, **data) -> None:
    await hass.services.async_call(domain, service, {"entity_id": entity_id, **data}, blocking=True)
    await hass.async_block_till_done()


async def test_auto_unlock_on_and_expires(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _call(hass, "switch", "turn_on", AUTO)
    params = ring.rpcs("set_autounlock_mode")[-1]
    assert params["user_id"] == str(USER_ID)
    assert params["enabled"] is True
    assert params["waiting_interval"] == 60
    assert params["anyring"] == 0
    assert params["origin"] == "user"
    assert params["issue_time"] > 1_700_000_000_000  # Millisekunden wie die App
    assert hass.states.get(AUTO).state == "on"
    assert hass.states.get(AUTO).attributes["until"] is not None  # englischer Schlüssel, übersetzt als „Bis“

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "off"


async def test_auto_unlock_off(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _call(hass, "switch", "turn_on", AUTO)
    await _call(hass, "switch", "turn_off", AUTO)
    params = ring.rpcs("set_autounlock_mode")[-1]
    assert params["enabled"] is False
    assert params["waiting_interval"] == 0
    assert hass.states.get(AUTO).state == "off"


async def test_ding_consumes_auto_unlock_and_polls_call(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry
) -> None:
    await _call(hass, "switch", "turn_on", AUTO)
    hass.states.async_set(DING_ENTITY, "2026-10-12T10:05:00.000+00:00", {"event_type": "ding"})
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "off"
    assert hass.states.get("binary_sensor.front_door_anruf_aktiv").state == "on"

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_anruf_aktiv").state == "off"
    assert len(ring.rpcs("active_call")) == 2
    assert ring.rpcs("active_call")[0]["command_timeout"] == 5


async def test_unlock_duration(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _call(hass, "number", "set_value", "number.front_door_offnungsdauer", value=5)
    method, url, body = ring.calls[-1]
    assert (method, url) == ("PATCH", f"/devices/v1/devices/{DEVICE_API_ID}/settings")
    sent = body["intercom_settings"]
    config = json.loads(sent["config"])
    assert config["analog"] == {"unlock_duration": 5000, "audio_amp": 2}  # Rest bleibt erhalten
    assert sent["ring_to_open"] is False
    assert sent["unlock_mode"] == 0
    assert "mic_index" not in sent  # null weglassen wie Gson
    assert hass.states.get("number.front_door_offnungsdauer").state == "5"


async def test_ring_to_open(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _call(hass, "switch", "turn_on", "switch.front_door_ring_to_open")
    sent = ring.calls[-1][2]["intercom_settings"]
    assert sent["ring_to_open"] is True
    assert sent["config"] == ring.settings["config"]
    assert hass.states.get("switch.front_door_ring_to_open").state == "on"


async def test_reboot(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _call(hass, "button", "press", "button.front_door_neustart")
    assert ring.calls[-1] == ("PATCH", f"/commands/v1/devices/{DEVICE_API_ID}", {"command_name": "reboot"})


async def test_rpc_error(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    ring.rpc_error = {"code": -32601, "message": "Method not found"}
    with pytest.raises(HomeAssistantError, match="Method not found"):
        await _call(hass, "switch", "turn_on", AUTO)
    assert hass.states.get(AUTO).state == "off"


async def test_ding_sensor_like_ring_mqtt(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    hass.states.async_set(DING_ENTITY, "2026-10-12T10:06:00.000+00:00", {"event_type": "ding"})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_klingel").state == "on"
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=21))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_klingel").state == "off"


async def test_lock_opens_door(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _call(hass, "lock", "unlock", "lock.front_door_turoffner")
    assert ring.rpcs("unlock_door") == [{"door_id": 0, "user_id": -1}]
    assert hass.states.get("lock.front_door_turoffner").state == "unlocked"
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert hass.states.get("lock.front_door_turoffner").state == "locked"


async def test_lock_shows_app_unlock(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    hass.states.async_set(UNLOCK_ENTITY, "2026-10-12T10:07:00.000+00:00", {"event_type": "intercom_unlock"})
    await hass.async_block_till_done()
    assert hass.states.get("lock.front_door_turoffner").state == "unlocked"
    assert ring.rpcs("unlock_door") == []  # nur angezeigt, nichts gesendet


async def test_lock_does_nothing(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    calls = len(ring.calls)
    await _call(hass, "lock", "lock", "lock.front_door_turoffner")
    assert len(ring.calls) == calls


async def test_lock_with_pin(hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry) -> None:
    """Mit PIN in den Optionen öffnet lock.unlock nur noch mit dem richtigen Code."""
    hass.config.language = "de"
    entry = MockConfigEntry(domain=DOMAIN, title="Ring Intercom Plus", data={}, options={"unlock_code": "1234"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    lock = "lock.front_door_turoffner"
    assert hass.states.get(lock).attributes["code_format"] == r"^\d{4,8}$"
    with pytest.raises(ServiceValidationError):  # HA prüft das Format: kein Code
        await _call(hass, "lock", "unlock", lock)
    with pytest.raises(ServiceValidationError, match="Wrong PIN"):
        await _call(hass, "lock", "unlock", lock, code="9999")
    assert ring.rpcs("unlock_door") == []
    assert hass.states.get(lock).state == "locked"
    await _call(hass, "lock", "unlock", lock, code="1234")
    assert ring.rpcs("unlock_door") == [{"door_id": 0, "user_id": -1}]
    assert hass.states.get(lock).state == "unlocked"


async def test_lock_without_pin_has_no_code_field(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    assert "code_format" not in hass.states.get("lock.front_door_turoffner").attributes


async def test_active_call_error_is_harmless(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    ring.active_call_error = True
    hass.states.async_set(DING_ENTITY, "2026-10-12T10:05:00.000+00:00", {"event_type": "ding"})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_klingel").state == "on"
    assert hass.states.get("binary_sensor.front_door_anruf_aktiv").state == "off"
    assert setup.runtime_data.intercoms[0]._call_timer is None  # kein weiteres Nachfragen


async def test_unload_cancels_timers(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _call(hass, "switch", "turn_on", AUTO)
    hass.states.async_set(DING_ENTITY, "2026-10-12T10:05:00.000+00:00", {"event_type": "ding"})
    await hass.async_block_till_done()
    hass.states.async_set(UNLOCK_ENTITY, "2026-10-12T10:05:01.000+00:00", {"event_type": "intercom_unlock"})
    await hass.async_block_till_done()
    coordinator = setup.runtime_data.intercoms[0]
    assert coordinator._ding_timer and coordinator._unlock_timer and coordinator._call_timer
    assert await hass.config_entries.async_unload(setup.entry_id)
    await hass.async_block_till_done()
    assert coordinator._ding_timer is None and coordinator._unlock_timer is None
    assert coordinator._call_timer is None and coordinator._auto_unlock_timer is None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=120))
    await hass.async_block_till_done()  # kein Termin schreibt mehr in entladene Entitäten


async def test_second_ding_replaces_running_call_poll(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry
) -> None:
    """Klingelt es, während noch eine active_call-Abfrage läuft, läuft danach nur eine Kette weiter."""
    coordinator = setup.runtime_data.intercoms[0]
    gate = asyncio.Event()
    original = coordinator.api.async_active_call

    async def slow() -> bool:
        await gate.wait()
        return await original()

    coordinator.api.async_active_call = slow  # type: ignore[method-assign]
    coordinator.async_handle_ding()
    await asyncio.sleep(0)
    first = coordinator._call_task
    coordinator.async_handle_ding()
    await asyncio.sleep(0)
    assert first is not None and first.cancelled()
    gate.set()
    await hass.async_block_till_done()
    assert len(ring.rpcs("active_call")) == 1


async def test_settings_error_is_translated(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    coordinator = setup.runtime_data.intercoms[0]

    async def broken() -> dict:
        raise RuntimeError("Cloud weg")

    coordinator.api.async_get_intercom_settings = broken  # type: ignore[method-assign]
    with pytest.raises(UpdateFailed) as err:
        await coordinator._async_update_data()
    assert err.value.translation_key == "settings_unreadable"


def test_unlock_duration_unreadable() -> None:
    assert unlock_duration({"config": json.dumps({"analog": {"unlock_duration": "kaputt"}})}) is None
    assert unlock_duration({"config": json.dumps({"analog": {}})}) == 3
    assert unlock_duration({"config": "kein json"}) is None


def _activity(hass: HomeAssistant, when: datetime) -> None:
    stamp = when.isoformat()
    hass.states.async_set(ACTIVITY_ENTITY, stamp, {"category": "ding", "created_at": stamp})


async def test_ding_without_push_comes_from_last_activity(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    """Fällt der Push aus, erkennt Ring Intercom Plus das Klingeln über „Letzte Aktivität“ (etwas später)."""
    _activity(hass, dt_util.utcnow() - timedelta(seconds=40))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_klingel").state == "on"
    assert setup.runtime_data.intercoms[0].push_misses == 1


async def test_ding_by_push_is_not_counted_twice(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    coordinator = setup.runtime_data.intercoms[0]
    calls: list[None] = []
    original = coordinator.async_handle_ding
    coordinator.async_handle_ding = lambda: (calls.append(None), original())[1]  # type: ignore[method-assign]
    now = dt_util.utcnow()
    hass.states.async_set(DING_ENTITY, now.isoformat(), {"event_type": "ding"})
    await hass.async_block_till_done()
    _activity(hass, now - timedelta(seconds=2))
    await hass.async_block_till_done()
    assert len(calls) == 1 and coordinator.push_misses == 0


async def test_old_or_other_activity_is_ignored(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    _activity(hass, dt_util.utcnow() - timedelta(minutes=10))  # z. B. alter Stand nach einem Neustart
    await hass.async_block_till_done()
    stamp = dt_util.utcnow().isoformat()
    hass.states.async_set(ACTIVITY_ENTITY, stamp, {"category": "motion", "created_at": stamp})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_klingel").state == "off"


async def test_repair_issue_while_push_is_missing(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    coordinator = setup.runtime_data.intercoms[0]
    issue_id = f"push_missing_{coordinator.ring_device_id}"
    for seconds in (90, 30):
        _activity(hass, dt_util.utcnow() - timedelta(seconds=seconds))
        await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
    await hass.async_block_till_done()
    hass.states.async_set(DING_ENTITY, dt_util.utcnow().isoformat(), {"event_type": "ding"})
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert coordinator.push_misses == 0
