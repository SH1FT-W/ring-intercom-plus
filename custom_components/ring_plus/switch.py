"""Schalter: „Nächstes Klingeln öffnet“ und „Ring-to-Open“."""

from __future__ import annotations

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
        if coordinator.user_id is not None:
            entities.append(AutoUnlockSwitch(coordinator))
        if "ring_to_open" in (coordinator.data or {}):
            entities.append(RingToOpenSwitch(coordinator))
    async_add_entities(entities)


class AutoUnlockSwitch(RingPlusEntity, SwitchEntity):
    """An = das nächste Klingeln innerhalb von 60 s öffnet die Tür; geht danach von selbst aus."""

    def __init__(self, coordinator: IntercomCoordinator) -> None:
        super().__init__(coordinator, "auto_unlock")

    @property
    def is_on(self) -> bool:
        return self.coordinator.auto_unlock_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        until = self.coordinator.auto_unlock_until
        return {"until": until.isoformat() if until and self.coordinator.auto_unlock_active else None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        await self._run(self.coordinator.async_set_auto_unlock(enabled))


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
