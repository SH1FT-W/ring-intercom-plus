"""Next ring opens: time window, schedule, restarts. Opening the door is the risky part, so most tests check
that the door stays closed when it should."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from conftest import ACTIVITY_ENTITY, DING_ENTITY, UNLOCK_ENTITY
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
import voluptuous as vol

from common import DEVICE_API_ID, FakeRing, push_alert
from custom_components.ring_plus.const import DOMAIN
from custom_components.ring_plus.storage import STORAGE_KEY

AUTO = "switch.front_door_nachstes_klingeln_offnet"
WINDOW = "number.front_door_nachstes_klingeln_offnet_zeitfenster"
LOCK = "lock.front_door_turoffner"
SCHEDULE = "schedule.deliveries"


async def _call(hass: HomeAssistant, domain: str, service: str, entity_id: str, **data: Any) -> None:
    await hass.services.async_call(domain, service, {"entity_id": entity_id, **data}, blocking=True)
    await hass.async_block_till_done()


async def _ding(hass: HomeAssistant, when: datetime | None = None, alert_id: int | None = None) -> None:
    """Push ding: Ring's alert (own id and time) plus the event entity firing, as the Ring integration does."""
    if alert_id != 0:
        push_alert(hass, "ding", when, alert_id)
    await _fire(hass, DING_ENTITY, "ding")


_fired = iter(range(1, 1_000_000))


async def _fire(hass: HomeAssistant, entity_id: str, event_type: str) -> None:
    """The event entity fires (new state); it does so again for every event of the device while an alert lives."""
    stamp = dt_util.utcnow() + timedelta(microseconds=next(_fired))
    hass.states.async_set(entity_id, stamp.isoformat(), {"event_type": event_type})
    await hass.async_block_till_done()


async def _saved(hass: HomeAssistant, hass_storage: dict[str, Any]) -> dict[str, Any]:
    async_fire_time_changed(hass, dt_util.utcnow())  # delayed write with delay 0
    await hass.async_block_till_done()
    return hass_storage[STORAGE_KEY]["data"][str(DEVICE_API_ID)]


async def _setup(hass: HomeAssistant, options: dict[str, Any] | None = None) -> MockConfigEntry:
    hass.config.language = "de"
    entry = MockConfigEntry(domain=DOMAIN, title="Ring Intercom Plus", data={}, options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _window(hass: HomeAssistant, minutes: int) -> None:
    await _call(hass, "number", "set_value", WINDOW, value=minutes)


# ---------- Default stays as before ----------


async def test_default_window_is_the_intercoms_60_seconds(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry
) -> None:
    assert hass.states.get(WINDOW).state == "1"
    await _call(hass, "switch", "turn_on", AUTO)
    assert ring.rpcs("set_autounlock_mode")[-1]["waiting_interval"] == 60
    assert hass.states.get(AUTO).attributes["mode"] == "ring"
    await _ding(hass)
    assert ring.rpcs("unlock_door") == []  # the intercom opens itself, Home Assistant sends nothing
    assert hass.states.get(AUTO).state == "off"


# ---------- Time window (Home Assistant opens) ----------


async def test_window_opens_on_next_push_ding_once(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    assert ring.rpcs("set_autounlock_mode") == []  # nothing armed at the intercom
    state = hass.states.get(AUTO)
    assert state.state == "on" and state.attributes["mode"] == "window"
    until = dt_util.parse_datetime(state.attributes["until"])
    assert until is not None and timedelta(minutes=29) < until - dt_util.utcnow() <= timedelta(minutes=30)

    await _ding(hass)
    assert ring.rpcs("unlock_door") == [{"door_id": 0, "user_id": -1}]
    assert hass.states.get(AUTO).state == "off"  # "next ring": used up
    assert hass.states.get(LOCK).state == "unlocked"
    assert hass.states.get("sensor.front_door_zuletzt_geoffnet").attributes["source"] == "auto_unlock"

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=1))
    await hass.async_block_till_done()
    await _ding(hass)
    assert len(ring.rpcs("unlock_door")) == 1  # the second ring does not open


async def test_window_expires(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry, hass_storage) -> None:
    await _window(hass, 15)
    await _call(hass, "switch", "turn_on", AUTO)
    assert (await _saved(hass, hass_storage))["until"] is not None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=15, seconds=1))
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "off"
    assert (await _saved(hass, hass_storage))["until"] is None
    await _ding(hass)
    assert ring.rpcs("unlock_door") == []


async def test_window_old_ring_does_not_open(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    """Ring's own time of the ring counts: a late push or a replay after a restart never opens."""
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    await _ding(hass, dt_util.utcnow() - timedelta(seconds=100))
    assert ring.rpcs("unlock_door") == []
    assert hass.states.get(AUTO).state == "on"


async def test_window_event_without_alert_does_not_open(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry
) -> None:
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    await _ding(hass, alert_id=0)  # event entity fires, but Ring has no active ding alert
    assert ring.rpcs("unlock_door") == []


async def test_window_ring_structure_changed_fails_closed(
    hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry, setup: MockConfigEntry
) -> None:
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    del ring_entry.runtime_data.listen_coordinator
    await _fire(hass, DING_ENTITY, "ding")
    assert ring.rpcs("unlock_door") == []
    assert hass.states.get("binary_sensor.front_door_klingel").state == "on"  # the ding itself still shows


async def test_window_armed_after_ring_does_not_open_on_refire(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry
) -> None:
    """Rang before arming; the Ring integration fires the ding entity again on the next unlock push."""
    push_alert(hass, "ding", dt_util.utcnow() - timedelta(seconds=10))
    await _fire(hass, DING_ENTITY, "ding")
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    push_alert(hass, "intercom_unlock")
    await _fire(hass, UNLOCK_ENTITY, "intercom_unlock")
    await _fire(hass, DING_ENTITY, "ding")  # same, still active ding alert
    assert ring.rpcs("unlock_door") == []
    assert hass.states.get(AUTO).state == "on"


async def test_window_ding_without_push_does_not_open(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry
) -> None:
    """A ring only seen in "last activity" (about a minute late) does not open, the window stays."""
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    stamp = (dt_util.utcnow() - timedelta(seconds=40)).isoformat()
    hass.states.async_set(ACTIVITY_ENTITY, stamp, {"category": "ding", "created_at": stamp})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_klingel").state == "on"
    assert ring.rpcs("unlock_door") == []
    assert hass.states.get(AUTO).state == "on"


async def test_window_off_sends_nothing_and_stays_off(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry, hass_storage
) -> None:
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    await _call(hass, "switch", "turn_off", AUTO)
    assert ring.rpcs("set_autounlock_mode") == []
    assert hass.states.get(AUTO).state == "off"
    assert (await _saved(hass, hass_storage))["until"] is None
    await _ding(hass)
    assert ring.rpcs("unlock_door") == []


async def test_window_open_fails_keeps_window(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    ring.rpc_error = {"code": 1, "message": "offline"}
    await _ding(hass)
    assert hass.states.get(AUTO).state == "on"  # the next ring tries again
    assert hass.states.get("sensor.front_door_zuletzt_geoffnet").state == "unknown"


async def test_same_ring_fired_twice_opens_once(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    coordinator = setup.runtime_data.intercoms[0]
    gate = asyncio.Event()
    original = coordinator.api.async_unlock_door

    async def slow() -> None:
        await gate.wait()
        await original()

    coordinator.api.async_unlock_door = slow  # type: ignore[method-assign]
    push_alert(hass, "ding")
    coordinator.async_handle_push_ding()
    await asyncio.sleep(0)
    coordinator.async_handle_push_ding()
    gate.set()
    await hass.async_block_till_done()
    assert len(ring.rpcs("unlock_door")) == 1


async def test_switch_off_right_after_ring_cancels_opening(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry
) -> None:
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    coordinator = setup.runtime_data.intercoms[0]
    gate = asyncio.Event()
    original = coordinator.api.async_unlock_door

    async def slow() -> None:
        await gate.wait()
        await original()

    coordinator.api.async_unlock_door = slow  # type: ignore[method-assign]
    push_alert(hass, "ding")
    coordinator.async_handle_push_ding()
    await coordinator.async_set_auto_unlock(False)  # before the opening task got to send anything
    gate.set()
    await hass.async_block_till_done()
    assert ring.rpcs("unlock_door") == []
    assert hass.states.get(AUTO).state == "off"


async def test_switching_from_ring_mode_to_window_disarms_the_intercom(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry
) -> None:
    await _call(hass, "switch", "turn_on", AUTO)  # 60 s at the intercom
    await _call(hass, DOMAIN, "next_ring_opens", AUTO, duration={"hours": 2})
    assert [p["enabled"] for p in ring.rpcs("set_autounlock_mode")] == [True, False]
    state = hass.states.get(AUTO)
    assert state.attributes["mode"] == "window"
    until = dt_util.parse_datetime(state.attributes["until"])
    assert until is not None and until - dt_util.utcnow() > timedelta(minutes=119)


async def test_action_duration(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _call(hass, DOMAIN, "next_ring_opens", AUTO, duration="00:01:00")
    assert ring.rpcs("set_autounlock_mode")[-1]["waiting_interval"] == 60  # 1 minute = intercom mode
    await _call(hass, DOMAIN, "next_ring_opens", AUTO)  # default: the number (1 minute)
    assert hass.states.get(AUTO).attributes["mode"] == "ring"
    for too_long in ({"hours": 8, "minutes": 1}, {"seconds": 30}):
        with pytest.raises(vol.Invalid):
            await _call(hass, DOMAIN, "next_ring_opens", AUTO, duration=too_long)


async def test_action_on_other_switch_fails(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    with pytest.raises(ServiceValidationError, match="only on the switch"):
        await _call(hass, DOMAIN, "next_ring_opens", "switch.front_door_ring_to_open", duration={"hours": 1})
    assert ring.rpcs("set_autounlock_mode") == []


async def test_window_range_is_checked(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    coordinator = setup.runtime_data.intercoms[0]
    with pytest.raises(ServiceValidationError):
        await coordinator.async_set_auto_unlock_window(481)
    with pytest.raises(ServiceValidationError):
        await coordinator.async_set_auto_unlock(True, timedelta(hours=9))
    with pytest.raises(ServiceValidationError):
        await coordinator.async_set_auto_unlock(True, timedelta(seconds=10))
    assert not coordinator.auto_unlock_active


async def test_switch_stays_available_to_turn_off(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    """Settings unreadable: the switch must still be switchable off while the window is running."""
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    coordinator = setup.runtime_data.intercoms[0]

    async def broken() -> dict:
        raise RuntimeError("Cloud weg")

    coordinator.api.async_get_intercom_settings = broken  # type: ignore[method-assign]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("switch.front_door_ring_to_open").state == "unavailable"
    assert hass.states.get(AUTO).state == "on"
    await _call(hass, "switch", "turn_off", AUTO)
    assert hass.states.get(AUTO).state == "off"


# ---------- Restarts and reloads ----------


async def test_window_survives_reload(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    await _window(hass, 60)
    await _call(hass, "switch", "turn_on", AUTO)
    assert await hass.config_entries.async_reload(setup.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "on"
    assert hass.states.get(WINDOW).state == "60"
    await _ding(hass)
    assert len(ring.rpcs("unlock_door")) == 1
    # used up before the reload = stays used up after it
    assert await hass.config_entries.async_reload(setup.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "off"


def _stored(**values: Any) -> dict[str, Any]:
    return {"version": 1, "minor_version": 1, "key": STORAGE_KEY, "data": {str(DEVICE_API_ID): values}}


async def test_window_survives_restart(
    hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry, hass_storage
) -> None:
    until = dt_util.utcnow() + timedelta(minutes=20)
    hass_storage[STORAGE_KEY] = _stored(window_minutes=30, until=until.isoformat())
    await _setup(hass)
    state = hass.states.get(AUTO)
    assert state.state == "on" and state.attributes["mode"] == "window"
    assert hass.states.get(WINDOW).state == "30"
    async_fire_time_changed(hass, until + timedelta(seconds=1))  # the timer runs on after the restart
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "off"


async def test_restart_does_not_open_for_ring_already_opened(
    hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry, hass_storage
) -> None:
    """Schedule: the ring Home Assistant opened for before the restart is replayed by Ring's listener."""
    when = dt_util.utcnow() - timedelta(seconds=5)
    hass_storage[STORAGE_KEY] = _stored(ding_key="77")
    _schedule(hass, "on")
    await _setup(hass, {"auto_unlock_schedule": SCHEDULE})
    await _ding(hass, when, alert_id=77)
    assert ring.rpcs("unlock_door") == []
    await _ding(hass)  # a new ring still opens
    assert len(ring.rpcs("unlock_door")) == 1


async def test_intercom_mode_survives_reload(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    """After a reload the switch still shows the armed 60 s and switching off disarms the intercom."""
    await _call(hass, "switch", "turn_on", AUTO)
    assert await hass.config_entries.async_reload(setup.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).attributes["mode"] == "ring"
    await _call(hass, "switch", "turn_off", AUTO)
    assert [p["enabled"] for p in ring.rpcs("set_autounlock_mode")] == [True, False]


@pytest.mark.parametrize(
    "values",
    [
        {"until": "2020-01-01T00:00:00+00:00"},  # expired while Home Assistant was down
        {"until": "2999-01-01T00:00:00+00:00"},  # longer than 8 hours: never accepted
        {"until": "kaputt", "window_minutes": 9999, "suspended": "yes"},
        {"until": "2026-11-02T10:00:00"},  # no time zone
        {"until": "2999-01-01T00:00:00+00:00", "mode": "ring"},  # the intercom mode lasts 60 s at most
        {"until": "2999-01-01T00:00:00+00:00", "mode": "kaputt"},
    ],
)
async def test_restart_ignores_old_or_broken_values(
    hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry, hass_storage, values: dict[str, Any]
) -> None:
    hass_storage[STORAGE_KEY] = _stored(**values)
    await _setup(hass)
    assert hass.states.get(AUTO).state == "off"
    assert hass.states.get(WINDOW).state == "1"
    await _ding(hass)
    assert ring.rpcs("unlock_door") == []


async def test_restart_ignores_broken_file(
    hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry, hass_storage
) -> None:
    hass_storage[STORAGE_KEY] = {"version": 1, "minor_version": 1, "key": STORAGE_KEY, "data": ["kaputt"]}
    await _setup(hass)
    assert hass.states.get(AUTO).state == "off"


async def test_remove_entry_deletes_saved_state(hass: HomeAssistant, setup: MockConfigEntry, hass_storage) -> None:
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    await _saved(hass, hass_storage)
    assert STORAGE_KEY in hass_storage
    assert await hass.config_entries.async_remove(setup.entry_id)
    await hass.async_block_till_done()
    assert STORAGE_KEY not in hass_storage


# ---------- Schedule ----------


def _schedule(hass: HomeAssistant, state: str, next_event: datetime | None = None) -> None:
    attributes: dict[str, Any] = {"next_event": next_event} if next_event else {}
    hass.states.async_set(SCHEDULE, state, attributes)


def _paused(hass: HomeAssistant) -> bool:
    return bool(hass.config_entries.async_entries(DOMAIN)[0].runtime_data.intercoms[0]._suspended)


async def test_schedule_opens_every_ring_while_on(hass: HomeAssistant, ring: FakeRing, ring_entry) -> None:
    _schedule(hass, "on", dt_util.utcnow() + timedelta(hours=2))
    await _setup(hass, {"auto_unlock_schedule": SCHEDULE})
    state = hass.states.get(AUTO)
    assert state.state == "on" and state.attributes["mode"] == "schedule"
    assert state.attributes["until"] is None
    await _ding(hass)
    await _ding(hass, dt_util.utcnow() + timedelta(seconds=1))
    assert len(ring.rpcs("unlock_door")) == 2  # not used up
    assert hass.states.get(AUTO).state == "on"

    _schedule(hass, "off")
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "off"
    await _ding(hass, dt_util.utcnow() + timedelta(seconds=2))
    assert len(ring.rpcs("unlock_door")) == 2


@pytest.mark.parametrize("state", ["unavailable", "unknown", None])
async def test_schedule_missing_or_unavailable_is_off(
    hass: HomeAssistant, ring: FakeRing, ring_entry, state: str | None
) -> None:
    if state:
        _schedule(hass, state)
    await _setup(hass, {"auto_unlock_schedule": SCHEDULE})
    assert hass.states.get(AUTO).state == "off"
    await _ding(hass)
    assert ring.rpcs("unlock_door") == []


async def test_schedule_off_pauses_until_schedule_is_off(
    hass: HomeAssistant, ring: FakeRing, ring_entry, hass_storage
) -> None:
    _schedule(hass, "on", dt_util.utcnow() + timedelta(hours=2))
    entry = await _setup(hass, {"auto_unlock_schedule": SCHEDULE})
    await _call(hass, "switch", "turn_off", AUTO)
    assert ring.rpcs("set_autounlock_mode") == []  # nothing armed at the intercom, nothing to disarm
    assert hass.states.get(AUTO).state == "off"
    saved = await _saved(hass, hass_storage)
    assert saved["suspended"] is True and saved["suspended_for"] == SCHEDULE

    # the pause survives a reload and an unavailable or still missing schedule (restart, loading order)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    for state in ("unavailable", "unknown", "on"):
        _schedule(hass, state, dt_util.utcnow() + timedelta(hours=3))  # also a new next_event (attribute)
        await hass.async_block_till_done()
        assert _paused(hass)
    hass.states.async_remove(SCHEDULE)
    await hass.async_block_till_done()
    _schedule(hass, "on")
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "off"
    await _ding(hass)
    assert ring.rpcs("unlock_door") == []

    # only a real "off" ends the period: the next one is active again
    _schedule(hass, "off")
    await hass.async_block_till_done()
    assert (await _saved(hass, hass_storage))["suspended"] is False
    _schedule(hass, "on")
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "on"


async def test_pause_survives_restart_with_schedule_loading_late(
    hass: HomeAssistant, ring: FakeRing, ring_entry, hass_storage
) -> None:
    hass_storage[STORAGE_KEY] = _stored(suspended=True, suspended_for=SCHEDULE)
    await _setup(hass, {"auto_unlock_schedule": SCHEDULE})  # schedule not there yet
    _schedule(hass, "on")
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "off"
    await _ding(hass)
    assert ring.rpcs("unlock_door") == []


async def test_switch_on_during_paused_schedule_keeps_pause(hass: HomeAssistant, ring: FakeRing, ring_entry) -> None:
    _schedule(hass, "on", dt_util.utcnow() + timedelta(hours=2))
    await _setup(hass, {"auto_unlock_schedule": SCHEDULE})
    await _call(hass, "switch", "turn_off", AUTO)
    await _call(hass, "switch", "turn_on", AUTO)  # 1 minute = intercom mode only
    assert hass.states.get(AUTO).attributes["mode"] == "ring"
    assert _paused(hass)  # the schedule stays paused after the minute
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "off"


@pytest.mark.parametrize("options", [{}, {"auto_unlock_schedule": "schedule.other"}])
async def test_pause_dropped_when_schedule_removed_or_changed(
    hass: HomeAssistant, ring: FakeRing, ring_entry, hass_storage, options: dict[str, Any]
) -> None:
    hass_storage[STORAGE_KEY] = _stored(suspended=True, suspended_for=SCHEDULE)
    hass.states.async_set("schedule.other", "on")
    await _setup(hass, options)
    await _call(hass, "number", "set_value", WINDOW, value=2)  # any save
    assert (await _saved(hass, hass_storage))["suspended"] is False


@pytest.mark.parametrize("expected_lingering_timers", [True])  # the schedule helper's own timer
async def test_real_schedule_helper(hass: HomeAssistant, ring: FakeRing, ring_entry) -> None:
    """HA assumption: a schedule helper is "on" inside a period (entity_id from its config key)."""
    now = dt_util.now()
    start = (now - timedelta(minutes=5)).strftime("%H:%M:%S")
    end = (now + timedelta(minutes=30)).strftime("%H:%M:%S")
    if (now.hour == 23 and now.minute >= 25) or (now.hour == 0 and now.minute < 5):
        pytest.skip("period would cross midnight")
    weekday = now.strftime("%A").lower()
    assert await async_setup_component(
        hass, "schedule", {"schedule": {"deliveries": {"name": "Deliveries", weekday: [{"from": start, "to": end}]}}}
    )
    await hass.async_block_till_done()
    state = hass.states.get(SCHEDULE)
    assert state is not None and state.state == "on"

    await _setup(hass, {"auto_unlock_schedule": SCHEDULE})
    assert hass.states.get(AUTO).attributes["mode"] == "schedule"
    await _ding(hass)
    assert len(ring.rpcs("unlock_door")) == 1
    await _call(hass, "switch", "turn_off", AUTO)
    assert _paused(hass)
    await _ding(hass)
    assert len(ring.rpcs("unlock_door")) == 1


async def test_entry_unload_stops_schedule(hass: HomeAssistant, ring: FakeRing, ring_entry) -> None:
    _schedule(hass, "off")
    entry = await _setup(hass, {"auto_unlock_schedule": SCHEDULE})
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    _schedule(hass, "on")
    await hass.async_block_till_done()  # no listener writes to unloaded entities


async def test_refire_keeps_intercom_mode(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    """Rang, then 1 minute armed; a repeated event of that ring must not end the armed intercom mode."""
    await _ding(hass)
    await _call(hass, "switch", "turn_on", AUTO)
    await _fire(hass, DING_ENTITY, "ding")  # same alert, fired again by the Ring integration
    assert hass.states.get(AUTO).state == "on"


async def test_off_in_schedule_with_cloud_down_still_pauses(
    hass: HomeAssistant, ring: FakeRing, ring_entry, hass_storage
) -> None:
    """Switching off pauses the schedule even if Ring refuses to disarm the intercom's own minute."""
    _schedule(hass, "on")
    await _setup(hass, {"auto_unlock_schedule": SCHEDULE})
    await _call(hass, "switch", "turn_on", AUTO)  # 1 minute at the intercom
    ring.rpc_error = {"code": 1, "message": "offline"}
    with pytest.raises(HomeAssistantError):
        await _call(hass, "switch", "turn_off", AUTO)
    assert _paused(hass)
    assert (await _saved(hass, hass_storage))["suspended"] is True
    ring.rpc_error = None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    await _ding(hass)
    assert ring.rpcs("unlock_door") == []
    assert hass.states.get(AUTO).state == "off"


async def test_ring_reload_is_no_ding(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    """Ring reload: its event entities go unavailable and come back with the same state. Not a ring, no unlock."""
    await _call(hass, "switch", "turn_on", AUTO)
    for entity_id in (DING_ENTITY, UNLOCK_ENTITY):
        before = hass.states.get(entity_id)
        hass.states.async_set(entity_id, "unavailable")
        await hass.async_block_till_done()
        hass.states.async_set(entity_id, before.state, before.attributes)
        await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_klingel").state == "off"
    assert hass.states.get(LOCK).state == "locked"
    assert hass.states.get(AUTO).attributes["mode"] == "ring"


async def test_ring_reload_with_slow_listener_is_no_ding(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry
) -> None:
    """Ring reloads, Ring Intercom Plus reloads while Ring's entities are still unavailable, then they come back
    with their old state: still no ring, no unlock, and the armed minute stays shown."""
    await _call(hass, "switch", "turn_on", AUTO)
    before = {entity_id: hass.states.get(entity_id) for entity_id in (DING_ENTITY, UNLOCK_ENTITY)}
    for entity_id in before:
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(setup.entry_id)
    await hass.async_block_till_done()
    for entity_id, state in before.items():
        hass.states.async_set(entity_id, state.state, state.attributes)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.front_door_klingel").state == "off"
    assert hass.states.get(LOCK).state == "locked"
    assert hass.states.get(AUTO).attributes["mode"] == "ring"


async def test_off_restored_intercom_minute_without_user_id_says_so(
    hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry, hass_storage
) -> None:
    """Armed before a restart without user ID: cannot be disarmed, so it must not claim "off"."""
    until = dt_util.utcnow() + timedelta(seconds=40)
    hass_storage[STORAGE_KEY] = _stored(until=until.isoformat(), mode="ring")
    ring.profile_error = True
    await _setup(hass)
    with pytest.raises(ServiceValidationError, match="user ID"):
        await _call(hass, "switch", "turn_off", AUTO)
    assert hass.states.get(AUTO).state == "on"


async def test_unload_waits_for_sent_opening(hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry) -> None:
    """A reload while the door is being opened: the window is used up before the new entry loads."""
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    coordinator = setup.runtime_data.intercoms[0]
    gate = asyncio.Event()
    original = coordinator.api.async_unlock_door

    async def slow() -> None:
        await gate.wait()
        await original()

    coordinator.api.async_unlock_door = slow  # type: ignore[method-assign]
    push_alert(hass, "ding")
    coordinator.async_handle_push_ding()
    await asyncio.sleep(0)  # the opening task starts and waits at the gate (command "sent")
    reload = hass.async_create_task(hass.config_entries.async_reload(setup.entry_id))
    await asyncio.sleep(0)
    gate.set()
    assert await reload
    await hass.async_block_till_done()
    assert hass.states.get(AUTO).state == "off"
    await _ding(hass)
    assert len(ring.rpcs("unlock_door")) == 1


async def test_off_in_schedule_pause_saved_before_slow_disarm(
    hass: HomeAssistant, ring: FakeRing, ring_entry, hass_storage
) -> None:
    """Off during a schedule while the intercom's minute is armed: the pause is saved before Ring answers, so a
    reload (or a crash) while the disarm command is pending does not lose it."""
    _schedule(hass, "on")
    entry = await _setup(hass, {"auto_unlock_schedule": SCHEDULE})
    await _call(hass, "switch", "turn_on", AUTO)  # 1 minute at the intercom
    coordinator = entry.runtime_data.intercoms[0]
    gate = asyncio.Event()
    original = coordinator.api.async_set_auto_unlock

    async def slow(*args: Any, **kwargs: Any) -> None:
        await gate.wait()
        await original(*args, **kwargs)

    coordinator.api.async_set_auto_unlock = slow  # type: ignore[method-assign]
    turn_off = hass.async_create_task(
        hass.services.async_call("switch", "turn_off", {"entity_id": AUTO}, blocking=True)
    )
    for _ in range(5):
        await asyncio.sleep(0)  # the switch is off on the Home Assistant side, the disarm command waits at the gate
    assert await hass.config_entries.async_reload(entry.entry_id)  # while the command is pending
    gate.set()
    await turn_off
    await hass.async_block_till_done()
    assert _paused(hass)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    await _ding(hass)
    assert ring.rpcs("unlock_door") == []


async def test_unload_after_slow_opening_uses_up_window(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reload while an opening is still pending after the bounded wait: the window counts as used, so the
    reloaded entry does not open the door a second time on the next ring."""
    from custom_components.ring_plus import coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module, "OPEN_WAIT_ON_UNLOAD", 0.01)
    await _window(hass, 30)
    await _call(hass, "switch", "turn_on", AUTO)
    coordinator = setup.runtime_data.intercoms[0]
    gate = asyncio.Event()
    original = coordinator.api.async_unlock_door

    async def slow() -> None:
        await gate.wait()
        await original()

    coordinator.api.async_unlock_door = slow  # type: ignore[method-assign]
    push_alert(hass, "ding")
    coordinator.async_handle_push_ding()
    await asyncio.sleep(0)  # the opening task starts and waits at the gate (command "sent")
    assert await hass.config_entries.async_reload(setup.entry_id)  # the wait ends before the opening does
    assert hass.states.get(AUTO).state == "off"
    gate.set()
    await hass.async_block_till_done()
    await _ding(hass, dt_util.utcnow() + timedelta(seconds=1))
    assert len(ring.rpcs("unlock_door")) == 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))  # "unlocked" display of the late opening
    await hass.async_block_till_done()
