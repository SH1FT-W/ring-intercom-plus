"""Check the assumptions about the HA Ring integration against the real `homeassistant.components.ring`.

The other tests use a stand-in for the Ring config entry (`conftest.ring_entry`). Here the real Ring integration
of the installed HA version is set up instead; only the network below `ring_doorbell` is faked (Auth.async_query,
push listener). If HA changes `runtime_data.api` / `.devices.all_devices`, the unique_id formats of the
event/sensor entities, the device identifiers or the `last_activity` attributes, these tests fail.
See docs/ha-annahmen.md.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
import inspect
import json
import time
from typing import Any, ClassVar
from unittest.mock import patch

from homeassistant.components.ring.config_flow import RingConfigFlow
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from ring_doorbell import Auth, Ring, RingEvent
from ring_doorbell.const import API_URI

from common import DEVICE_API_ID, MAC, FakeRing
from custom_components.ring_plus.const import INTERCOM_KINDS

LOCATION_ID = "location-1"
INTERCOM: dict[str, Any] = {
    "id": DEVICE_API_ID,
    "description": "Front Door",
    "device_id": MAC,
    "kind": "intercom_handset_audio",
    "location_id": LOCATION_ID,
    "firmware_version": "1.0.0",
    "time_zone": "UTC",
    "settings": {"doorbell_volume": 5, "mic_volume": 5, "voice_volume": 5},
    "alerts": {"connection": "online"},
    "features": {"motion_detection_enabled": False},
}


class FakeListener:
    """Replaces ring_doorbell's push listener (FCM); `push` delivers an event like the real one."""

    instances: ClassVar[list[FakeListener]] = []

    def __init__(self, ring: Ring, *_: Any, **__: Any) -> None:
        self._ring = ring
        self.started = False
        self._callbacks: list[Callable[[RingEvent], None]] = []
        FakeListener.instances.append(self)

    async def start(self, **_: Any) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    def add_notification_callback(self, callback: Callable[[RingEvent], None]) -> int:
        self._callbacks.append(callback)
        return len(self._callbacks)

    def push(self, kind: str) -> None:
        event = RingEvent(
            id=int(time.time() * 1000),
            doorbot_id=DEVICE_API_ID,
            device_name=INTERCOM["description"],
            device_kind=INTERCOM["kind"],
            now=time.time(),
            expires_in=180,
            kind=kind,
            state="ringing",
        )
        self._ring._add_event_to_dings_data(event)  # same as the real listener
        for callback in self._callbacks:
            callback(event)


class FakeCloud:
    """Answers the Ring cloud below ring_doorbell.Auth; Ring Intercom Plus requests go to FakeRing."""

    def __init__(self, ring: FakeRing) -> None:
        self.ring = ring
        self.history: list[dict[str, Any]] = []

    async def query(self, url: str, method: str = "GET", json_body: Any = None) -> Any:
        path = url.removeprefix(API_URI)
        if path == "/clients_api/session":
            return {"profile": {"id": 1}}
        if path == "/clients_api/ring_devices":
            return {"other": [INTERCOM]}
        if path == "/clients_api/dings/active":
            return []
        if path == f"/groups/v1/locations/{LOCATION_ID}/groups":
            return {"device_groups": []}
        if path == f"/clients_api/doorbots/{DEVICE_API_ID}/health":
            return {"device_health": {}}
        if path == f"/clients_api/doorbots/{DEVICE_API_ID}/history":
            return self.history
        return (await self.ring.async_query(path, method=method, json=json_body)).json()


@pytest.fixture
def cloud(ring: FakeRing) -> FakeCloud:
    return FakeCloud(ring)


@pytest.fixture
def ring_patches(cloud: FakeCloud) -> Generator[None]:
    class FakeAuth:
        def __init__(self, *_: Any, **__: Any) -> None:
            return

        def get_hardware_id(self) -> str:
            return "hardware-id"

        def get_device_model(self) -> str:
            return "ha"

        async def async_query(
            self, url: str, method: str = "GET", json: Any = None, **_: Any
        ) -> Auth.Response:  # Ring.async_query ends here
            body = await cloud.query(url, method, json)
            return Auth.Response(_dumps(body), 200)

        async def async_close(self) -> None:
            return

    FakeListener.instances.clear()
    with (
        patch("homeassistant.components.ring.Auth", FakeAuth),
        patch("homeassistant.components.ring.coordinator.RingEventListener", FakeListener),
    ):
        yield


def _dumps(body: Any) -> bytes:
    return json.dumps(body).encode()


@pytest.fixture
async def ring_entry(hass: HomeAssistant, ring_patches: None) -> MockConfigEntry:
    """Overrides conftest.ring_entry: the real HA Ring integration instead of a stand-in."""
    entry = MockConfigEntry(
        domain="ring",
        title="Ring",
        data={"username": "user@example.com", "token": {"access_token": "x"}, "device_id": "hardware-id"},
        version=RingConfigFlow.VERSION,
        minor_version=RingConfigFlow.MINOR_VERSION,
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "ring", {})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _ring_entity(hass: HomeAssistant, platform: str, suffix: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, "ring", f"{DEVICE_API_ID}-{suffix}")
    assert entity_id is not None, f"HA Ring has no {platform} entity with unique_id {DEVICE_API_ID}-{suffix}"
    return entity_id


async def test_runtime_data_shape(hass: HomeAssistant, ring_entry: MockConfigEntry) -> None:
    """__init__.py: runtime_data.api.async_query and runtime_data.devices.all_devices."""
    data = ring_entry.runtime_data
    assert isinstance(data.api, Ring)
    assert inspect.iscoroutinefunction(data.api.async_query)
    params = inspect.signature(data.api.async_query).parameters
    assert {"url", "method", "json"} <= set(params)
    devices = list(data.devices.all_devices)
    assert len(devices) == 1
    device = devices[0]
    # Attributes Ring Intercom Plus reads from each device
    assert device.kind in INTERCOM_KINDS
    assert device.id == DEVICE_API_ID
    assert device.device_api_id == DEVICE_API_ID
    assert device.device_id == MAC
    assert device.name == "Front Door"


async def test_entity_unique_ids_and_device(hass: HomeAssistant, ring_entry: MockConfigEntry) -> None:
    """Event/sensor unique_ids `<api_id>-ding`, `-intercom_unlock`, `-last_activity`, device id = MAC."""
    device = dr.async_get(hass).async_get_device_by_identifier(("ring", MAC), ring_entry.entry_id)
    assert device is not None
    registry = er.async_get(hass)
    for platform, suffix in (("event", "ding"), ("event", "intercom_unlock"), ("sensor", "last_activity")):
        entry = registry.async_get(_ring_entity(hass, platform, suffix))
        assert entry is not None and entry.device_id == device.id


async def test_ring_plus_runs_on_real_ring(
    hass: HomeAssistant, ring: FakeRing, ring_entry: MockConfigEntry, setup: MockConfigEntry
) -> None:
    """Ring Intercom Plus loads on top, sends through Ring.async_query and attaches to the Ring device."""
    assert setup.state is ConfigEntryState.LOADED
    assert ("GET", f"/devices/v1/devices/{DEVICE_API_ID}/settings", None) in ring.calls
    device = dr.async_get(hass).async_get_device_by_identifier(("ring", MAC), ring_entry.entry_id)
    assert device is not None
    lock = er.async_get(hass).async_get(next(iter(hass.states.async_entity_ids("lock"))))
    assert lock is not None and lock.platform == "ring_plus" and lock.device_id == device.id


async def test_push_ding_and_unlock_reach_ring_plus(
    hass: HomeAssistant, ring_entry: MockConfigEntry, setup: MockConfigEntry
) -> None:
    """A push from the Ring integration (event entities) switches the ding sensor and the lock."""
    (listener,) = FakeListener.instances
    assert listener.started
    listener.push("ding")
    await hass.async_block_till_done()
    assert hass.states.get(_ring_entity(hass, "event", "ding")).attributes["event_type"] == "ring"
    assert hass.states.get("binary_sensor.front_door_klingel").state == "on"

    listener.push("intercom_unlock")
    await hass.async_block_till_done()
    assert hass.states.get("lock.front_door_turoffner").state == "unlocked"


async def test_last_activity_fallback_reaches_ring_plus(
    hass: HomeAssistant, cloud: FakeCloud, ring_entry: MockConfigEntry, setup: MockConfigEntry
) -> None:
    """Without push: the polled `last_activity` sensor carries `category` and `created_at` for the fallback."""
    assert hass.states.get("binary_sensor.front_door_klingel").state == "off"
    created = dt_util.utcnow().replace(microsecond=0)
    cloud.history = [{"id": 1, "kind": "ding", "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"), "answered": False}]
    await ring_entry.runtime_data.devices_coordinator.async_refresh()  # the regular poll of HA Ring
    await hass.async_block_till_done()
    state = hass.states.get(_ring_entity(hass, "sensor", "last_activity"))
    assert state.attributes["category"] == "ding"
    assert dt_util.parse_datetime(str(state.attributes["created_at"])) == created
    assert hass.states.get("binary_sensor.front_door_klingel").state == "on"
