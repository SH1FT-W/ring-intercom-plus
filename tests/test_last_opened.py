"""Sensor "Last opened": time and source, only from what Home Assistant and Ring actually report."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from conftest import ACTIVITY_ENTITY, UNLOCK_ENTITY
from homeassistant.core import Context, HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser, async_fire_time_changed

from common import DEVICE_API_ID, FakeRing, push_alert
from custom_components.ring_plus.const import DOMAIN
from custom_components.ring_plus.storage import STORAGE_KEY

SENSOR = "sensor.front_door_zuletzt_geoffnet"
LOCK = "lock.front_door_turoffner"
AUTO = "switch.front_door_nachstes_klingeln_offnet"


def _source(hass: HomeAssistant) -> Any:
    return hass.states.get(SENSOR).attributes["source"]


async def _unlock_push(hass: HomeAssistant, when=None, alert: bool = True) -> None:
    """Unlock push: Ring's alert (id, time) and the event entity firing."""
    if alert:
        push_alert(hass, "intercom_unlock", when)
    hass.states.async_set(UNLOCK_ENTITY, dt_util.utcnow().isoformat(), {"event_type": "intercom_unlock"})
    await hass.async_block_till_done()


async def _history(hass: HomeAssistant, category: str, when) -> None:
    stamp = when.isoformat()
    hass.states.async_set(ACTIVITY_ENTITY, stamp, {"category": category, "created_at": stamp})
    await hass.async_block_till_done()


async def test_ha_door_opener_with_user(hass: HomeAssistant, setup: MockConfigEntry, hass_admin_user: MockUser) -> None:
    assert hass.states.get(SENSOR).state == "unknown"
    assert _source(hass) is None
    await hass.services.async_call(
        "lock", "unlock", {"entity_id": LOCK}, blocking=True, context=Context(user_id=hass_admin_user.id)
    )
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.attributes["source"] == "home_assistant"
    assert state.attributes["user"] == hass_admin_user.name
    opened = dt_util.parse_datetime(state.state)
    assert opened is not None and abs(dt_util.utcnow() - opened) < timedelta(seconds=5)

    # Ring's unlock push for the same opening does not overwrite the source
    await _unlock_push(hass)
    assert _source(hass) == "home_assistant"
    # nor does Ring's history entry for it
    await _history(hass, "intercom_unlock", opened + timedelta(seconds=3))
    assert _source(hass) == "home_assistant"


async def test_ha_door_opener_from_automation_has_no_user(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    await hass.services.async_call("lock", "unlock", {"entity_id": LOCK}, blocking=True)
    await hass.async_block_till_done()
    assert _source(hass) == "home_assistant"
    assert hass.states.get(SENSOR).attributes["user"] is None


async def test_unlock_push_is_ring_app(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    await _unlock_push(hass)
    assert _source(hass) == "ring_app"
    assert hass.states.get(LOCK).state == "unlocked"


async def test_unlock_push_while_intercom_auto_unlock_is_armed_is_unknown(
    hass: HomeAssistant, setup: MockConfigEntry
) -> None:
    """The intercom's own 60 s mode may also send it: which one it was is not provable."""
    await hass.services.async_call("switch", "turn_on", {"entity_id": AUTO}, blocking=True)
    await _unlock_push(hass)
    assert _source(hass) == "unknown"


async def test_unlock_counts_once_with_rings_time(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    """The event entity fires again for later events of the device: the same alert counts once, at Ring's time."""
    when = (dt_util.utcnow() - timedelta(seconds=40)).replace(microsecond=0)
    await _unlock_push(hass, when)
    assert dt_util.parse_datetime(hass.states.get(SENSOR).state) == when
    await _unlock_push(hass, alert=False)  # re-fired, same alert
    assert dt_util.parse_datetime(hass.states.get(SENSOR).state) == when
    assert _source(hass) == "ring_app"


async def test_unlock_event_without_alert_is_not_an_opening(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    await _unlock_push(hass, alert=False)
    assert hass.states.get(SENSOR).state == "unknown"
    assert hass.states.get(LOCK).state == "unlocked"  # shown as before


async def test_ring_history_unlock(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    when = (dt_util.utcnow() - timedelta(minutes=30)).replace(microsecond=0)
    await _history(hass, "intercom_unlock", when)
    assert _source(hass) == "ring_history"
    assert dt_util.parse_datetime(hass.states.get(SENSOR).state) == when
    # an older history entry does not move the time back
    await _history(hass, "intercom_unlock", when - timedelta(hours=1))
    assert dt_util.parse_datetime(hass.states.get(SENSOR).state) == when
    # a ding is no opening
    await _history(hass, "ding", dt_util.utcnow())
    assert dt_util.parse_datetime(hass.states.get(SENSOR).state) == when


async def test_survives_reload_and_restart(
    hass: HomeAssistant, ring: FakeRing, setup: MockConfigEntry, hass_storage
) -> None:
    await _unlock_push(hass)
    before = hass.states.get(SENSOR).state
    assert await hass.config_entries.async_reload(setup.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == before
    assert _source(hass) == "ring_app"


async def test_restored_from_storage(hass: HomeAssistant, ring_entry: MockConfigEntry, hass_storage) -> None:
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            str(DEVICE_API_ID): {
                "last_opened": "2026-10-01T08:00:00+00:00",
                "last_opened_source": "home_assistant",
                "last_opened_user": "Alex",
            }
        },
    }
    hass.config.language = "de"
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert dt_util.parse_datetime(state.state) == dt_util.parse_datetime("2026-10-01T08:00:00+00:00")
    assert state.attributes == state.attributes | {"source": "home_assistant", "user": "Alex"}


async def test_broken_storage_values_are_dropped(
    hass: HomeAssistant, ring_entry: MockConfigEntry, hass_storage
) -> None:
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {str(DEVICE_API_ID): {"last_opened": None, "last_opened_source": "hacker", "last_opened_user": 5}},
    }
    hass.config.language = "de"
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.state == "unknown" and state.attributes["source"] is None and state.attributes["user"] is None


async def test_unlock_refire_does_not_show_unlocked_again(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    await _unlock_push(hass)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert hass.states.get(LOCK).state == "locked"
    await _unlock_push(hass, alert=False)  # same alert, fired again for another event of the device
    assert hass.states.get(LOCK).state == "locked"
