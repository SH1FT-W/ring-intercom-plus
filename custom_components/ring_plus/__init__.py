"""Ring Intercom Plus: zusätzliche Intercom-Funktionen neben der HA-Ring-Integration (gleiche Anmeldung)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.config_entries import SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntry, ConfigEntryChange, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .api import IntercomApi, RingResponse, async_get_user_id
from .const import INTERCOM_KINDS, RING_DOMAIN
from .coordinator import IntercomCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class RingPlusData:
    """Laufzeitdaten: ein Coordinator je Intercom."""

    intercoms: list[IntercomCoordinator] = field(default_factory=list)


type RingPlusConfigEntry = ConfigEntry[RingPlusData]


def _ring_entry(hass: HomeAssistant) -> ConfigEntry | None:
    for entry in hass.config_entries.async_entries(RING_DOMAIN):
        if entry.state is ConfigEntryState.LOADED and getattr(entry, "runtime_data", None) is not None:
            return entry
    return None


async def async_setup_entry(hass: HomeAssistant, entry: RingPlusConfigEntry) -> bool:
    """Intercoms aus der HA-Ring-Integration übernehmen."""
    ring_entry = _ring_entry(hass)
    if ring_entry is None:
        raise ConfigEntryNotReady("Die Ring-Integration ist noch nicht geladen")

    async def query(url: str, **kwargs: Any) -> RingResponse:
        # Bei jedem Aufruf neu nachschlagen: lädt Ring neu, gibt es ein neues Ring-Objekt
        current = _ring_entry(hass)
        if current is None:
            raise RuntimeError("Ring-Integration nicht geladen")
        response: RingResponse = await current.runtime_data.api.async_query(url, **kwargs)
        return response

    try:
        devices = list(ring_entry.runtime_data.devices.all_devices)
    except AttributeError as err:
        # Aufbau der HA-Ring-Integration hat sich geändert → im Log sichtbar statt still kaputt
        raise ConfigEntryNotReady(f"Ring-Integration hat einen unbekannten Aufbau: {err}") from err
    intercoms = [device for device in devices if getattr(device, "kind", None) in INTERCOM_KINDS]

    try:
        user_id = await async_get_user_id(query)
    except Exception as err:  # noqa: BLE001 – ohne ID fehlt nur „Nächstes Klingeln öffnet“
        _LOGGER.warning("Ring-Benutzer-ID nicht lesbar, Auto-Öffnen nicht verfügbar: %s", err)
        user_id = None

    device_registry = dr.async_get(hass)
    data = RingPlusData()
    for device in intercoms:
        device_entry = device_registry.async_get_device_by_identifier(
            (RING_DOMAIN, str(device.device_id)), ring_entry.entry_id
        )
        if device_entry is None:
            _LOGGER.warning("Ring-Gerät %s nicht gefunden, Entitäten ohne Gerät", device.name)
        coordinator = IntercomCoordinator(
            hass,
            entry,
            IntercomApi(query, int(device.id)),
            ring_device_id=str(device.device_id),
            name=str(device.name),
            user_id=user_id,
            device_entry=device_entry,
        )
        await coordinator.async_config_entry_first_refresh()
        data.intercoms.append(coordinator)
    await asyncio.gather(*(coordinator.async_load_hw_revision() for coordinator in data.intercoms))

    entry.runtime_data = data
    _listen_for_dings(hass, entry)
    _watch_ring_entry(hass, entry, ring_entry)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: RingPlusConfigEntry) -> None:
    """Optionen (PIN) geändert: Eintrag neu laden, damit das Schloss das Code-Feld zeigt oder versteckt."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


def _listen_for_dings(hass: HomeAssistant, entry: RingPlusConfigEntry) -> None:
    """Klingeln/Entsperren der HA-Ring-Integration (event.*) mitlesen, keine zweite Push-Verbindung.

    Die Handler hängen an Entity-IDs; wird ein Ring-Ereignis umbenannt, neu angelegt oder gelöscht,
    werden sie über die Registry-Ereignisse neu aufgesetzt.
    """
    registry = er.async_get(hass)
    # (Plattform, unique_id) → (Gerätename, Handler mit dem neuen Zustand)
    by_unique_id: dict[tuple[str, str], tuple[str, Callable[[State], None]]] = {}
    for coordinator in entry.runtime_data.intercoms:
        api_id = coordinator.api.device_api_id
        by_unique_id[("event", f"{api_id}-ding")] = (
            coordinator.device_name,
            _ignore_state(coordinator.async_handle_push_ding),
        )
        by_unique_id[("event", f"{api_id}-intercom_unlock")] = (
            coordinator.device_name,
            _ignore_state(coordinator.async_handle_unlock),
        )
        # Ersatzweg, wenn der Push ausfällt: die Ring-Integration fragt „Letzte Aktivität“ regelmäßig ab
        by_unique_id[("sensor", f"{api_id}-last_activity")] = (coordinator.device_name, _activity_handler(coordinator))
    handlers: dict[str, Callable[[State], None]] = {}
    unsubscribe: list[CALLBACK_TYPE] = []

    @callback
    def _changed(event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if old is None or new is None or new.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) or new.state == old.state:
            return
        if handler := handlers.get(event.data["entity_id"]):
            handler(new)

    @callback
    def _subscribe() -> None:
        for cancel in unsubscribe:
            cancel()
        unsubscribe.clear()
        handlers.clear()
        for (platform, unique_id), (device_name, handler) in by_unique_id.items():
            if entity_id := registry.async_get_entity_id(platform, RING_DOMAIN, unique_id):
                handlers[entity_id] = handler
            else:
                _LOGGER.info("Ring-Entität %s für %s nicht gefunden", unique_id.rsplit("-", 1)[-1], device_name)
        if handlers:
            unsubscribe.append(async_track_state_change_event(hass, list(handlers), _changed))

    @callback
    def _registry_updated(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        data = event.data
        entity_id = data["entity_id"]
        if entity_id in handlers or data.get("old_entity_id") in handlers:
            _subscribe()  # umbenannt oder gelöscht
            return
        if data["action"] != "create":
            return
        created = registry.async_get(entity_id)
        if (
            created is not None
            and created.platform == RING_DOMAIN
            and (created.domain, created.unique_id) in by_unique_id
        ):
            _subscribe()  # Ring-Ereignis ist nachträglich aufgetaucht

    _subscribe()
    entry.async_on_unload(hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _registry_updated))

    @callback
    def _stop() -> None:
        for cancel in unsubscribe:
            cancel()
        unsubscribe.clear()

    entry.async_on_unload(_stop)


def _ignore_state(handler: Callable[[], None]) -> Callable[[State], None]:
    @callback
    def _call(_state: State) -> None:
        handler()

    return _call


def _activity_handler(coordinator: IntercomCoordinator) -> Callable[[State], None]:
    @callback
    def _call(state: State) -> None:
        category = state.attributes.get("category")
        created = dt_util.parse_datetime(str(state.attributes.get("created_at") or state.state))
        coordinator.async_handle_activity(str(category) if category else None, created)

    return _call


def _watch_ring_entry(hass: HomeAssistant, entry: RingPlusConfigEntry, ring_entry: ConfigEntry) -> None:
    """Wird der Ring-Eintrag neu geladen oder entfernt, Ring Intercom Plus neu laden.

    Sonst zeigen die Entitäten mit dem alten Ring-Objekt dauerhaft „nicht verfügbar“.
    """
    last_state = {"value": ring_entry.state}

    @callback
    def _entry_changed(change: ConfigEntryChange, changed: ConfigEntry) -> None:
        if changed.domain != RING_DOMAIN:
            return
        if change is ConfigEntryChange.REMOVED:
            reload = True
        else:
            # Nur der Wechsel nach „geladen“ zählt; Datenänderungen (Ring speichert Tokens) lösen nichts aus
            reload = changed.state is ConfigEntryState.LOADED and last_state["value"] is not ConfigEntryState.LOADED
            last_state["value"] = changed.state
        if reload:
            _LOGGER.debug("Ring-Eintrag %s (%s): Ring Intercom Plus wird neu geladen", changed.title, change)
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, _entry_changed))


async def async_unload_entry(hass: HomeAssistant, entry: RingPlusConfigEntry) -> bool:
    for coordinator in entry.runtime_data.intercoms:
        coordinator.async_shutdown_timers()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
