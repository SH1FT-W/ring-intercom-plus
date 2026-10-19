"""Binärsensoren: Klingel und „Anruf aktiv“."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RingPlusConfigEntry
from .coordinator import IntercomCoordinator
from .entity import RingPlusEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: RingPlusConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(
        entity
        for coordinator in entry.runtime_data.intercoms
        for entity in (ActiveCallSensor(coordinator), DingSensor(coordinator))
    )


class ActiveCallSensor(RingPlusEntity, BinarySensorEntity):
    """Wird nach jedem Klingeln abgefragt (alle 10 s, bis das Gespräch endet, höchstens 3 Min)."""

    def __init__(self, coordinator: IntercomCoordinator) -> None:
        super().__init__(coordinator, "active_call")

    @property
    def is_on(self) -> bool:
        # Vor dem ersten Klingeln unbekannt → aus (kein Dauer-Polling in die Cloud)
        return bool(self.coordinator.active_call)


class DingSensor(RingPlusEntity, BinarySensorEntity):
    """Klingel: 20 s an nach jedem Klingeln (wie der Klingel-Sensor von ring-mqtt)."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: IntercomCoordinator) -> None:
        super().__init__(coordinator, "ding")

    @property
    def is_on(self) -> bool:
        return self.coordinator.ding
