"""Schalter: „Nächstes Klingeln öffnet“ und „Ring-to-Open“."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RingPlusConfigEntry
from .coordinator import IntercomCoordinator
from .entity import RingPlusEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: RingPlusConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    entities: list[SwitchEntity] = []
    for coordinator in entry.runtime_data.intercoms:
        # Always there, also without the Ring user ID: it is the only way to switch a running window off
        entities.append(AutoUnlockSwitch(coordinator))
        if "ring_to_open" in (coordinator.data or {}):
            entities.append(RingToOpenSwitch(coordinator))
    async_add_entities(entities)


class AutoUnlockSwitch(RingPlusEntity, SwitchEntity):
    """On = the next ring opens the door; turns itself off at the end of the window.

    Window 1 minute (default): the intercom's own 60 s mode, as before. Longer windows (up to 8 h, number entity
    or action duration): Home Assistant opens the door when the next ring arrives by push. With a schedule in
    the options, the switch is also on while the schedule is on (every ring opens); off pauses the period.
    """

    def __init__(self, coordinator: IntercomCoordinator) -> None:
        super().__init__(coordinator, "auto_unlock")

    @property
    def available(self) -> bool:
        # Must stay switchable off while the settings cannot be read: Home Assistant's window or the schedule
        # keep opening the door on a ring regardless of the settings poll
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.auto_unlock_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mode = self.coordinator.auto_unlock_active_mode
        until = self.coordinator.auto_unlock_until
        return {
            "until": until.isoformat() if until and mode in ("ring", "window") else None,
            "mode": mode,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._run(self.coordinator.async_set_auto_unlock(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._run(self.coordinator.async_set_auto_unlock(False))

    async def async_next_ring_opens(self, duration: timedelta | None = None) -> None:
        """Action ring_plus.next_ring_opens: switch on for `duration` (default: the configured window)."""
        await self._run(self.coordinator.async_set_auto_unlock(True, duration))


class RingToOpenSwitch(RingPlusEntity, SwitchEntity):
    """An = „Ring-to-Open“, aus = „Direkt öffnen“ (Einstellung aus der Ring-App)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: IntercomCoordinator) -> None:
        super().__init__(coordinator, "ring_to_open")

    @property
    def is_on(self) -> bool | None:
        value = (self.coordinator.data or {}).get("ring_to_open")
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        settings = await self._run(self.coordinator.api.async_set_ring_to_open(self.coordinator.data, enabled))
        self.coordinator.async_set_updated_data(settings)
