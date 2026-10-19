"""Zahl: Öffnungsdauer des Türöffners (nur analoge Anlagen)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RingPlusConfigEntry
from .api import unlock_duration
from .const import UNLOCK_DURATION_MAX, UNLOCK_DURATION_MIN
from .coordinator import IntercomCoordinator
from .entity import RingPlusEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: RingPlusConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(
        UnlockDurationNumber(coordinator)
        for coordinator in entry.runtime_data.intercoms
        if unlock_duration(coordinator.data or {}) is not None
    )


class UnlockDurationNumber(RingPlusEntity, NumberEntity):
    """Wie lange der Türöffner summt."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = UNLOCK_DURATION_MIN
    _attr_native_max_value = UNLOCK_DURATION_MAX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: IntercomCoordinator) -> None:
        super().__init__(coordinator, "unlock_duration")

    @property
    def native_value(self) -> int | None:
        return unlock_duration(self.coordinator.data or {})

    async def async_set_native_value(self, value: float) -> None:
        settings = await self._run(self.coordinator.api.async_set_unlock_duration(self.coordinator.data, round(value)))
        self.coordinator.async_set_updated_data(settings)
