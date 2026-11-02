"""Persistent state per intercom (survives restarts and reloads).

One Store for the integration, kept in hass.data so a reload reads the in-memory copy instead of a file that a
pending write has not reached yet. Writes are scheduled without delay; HA flushes pending writes on shutdown.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.state"
EVENT_STATES_KEY = "_event_states"  # last real state of the Ring event entities, by unique_id
DATA_STATE: HassKey[PersistentState] = HassKey(f"{DOMAIN}_state")
_LOAD_LOCK: HassKey[asyncio.Lock] = HassKey(f"{DOMAIN}_state_lock")


class PersistentState:
    """`data[str(device_api_id)]` = dict with the saved values of one intercom."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, dict[str, Any]]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        loaded = await self._store.async_load()
        if isinstance(loaded, dict):
            self.data = {str(key): value for key, value in loaded.items() if isinstance(value, dict)}
            events = self.data.get(EVENT_STATES_KEY, {})
            self.data[EVENT_STATES_KEY] = {k: v for k, v in events.items() if isinstance(v, str)}

    def device(self, device_api_id: int) -> dict[str, Any]:
        return self.data.setdefault(str(device_api_id), {})

    @callback
    def async_save(self) -> None:
        self._store.async_delay_save(lambda: self.data, 0)

    async def async_remove(self) -> None:
        self.data = {}
        await self._store.async_remove()


async def async_get_state(hass: HomeAssistant) -> PersistentState:
    """Load once per run; later calls (reloads) get the same object."""
    lock = hass.data.setdefault(_LOAD_LOCK, asyncio.Lock())
    async with lock:
        if (state := hass.data.get(DATA_STATE)) is None:
            state = PersistentState(hass)
            await state.async_load()
            hass.data[DATA_STATE] = state
    return state
