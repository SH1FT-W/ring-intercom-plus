"""Sensors: last opened, plus diagnostics (hardware revision, intercom type, unlock mode)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RingPlusConfigEntry
from .coordinator import IntercomCoordinator
from .entity import RingPlusEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class RingPlusSensorDescription(SensorEntityDescription):
    value: Callable[[IntercomCoordinator], Any]


SENSORS: tuple[RingPlusSensorDescription, ...] = (
    RingPlusSensorDescription(key="hw_revision", value=lambda c: c.hw_revision),
    RingPlusSensorDescription(key="intercom_type", value=lambda c: (c.data or {}).get("intercom_type")),
    RingPlusSensorDescription(key="unlock_mode", value=lambda c: (c.data or {}).get("unlock_mode")),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: RingPlusConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    entities: list[SensorEntity] = []
    for coordinator in entry.runtime_data.intercoms:
        entities.append(LastOpenedSensor(coordinator))
        entities.extend(RingPlusSensor(coordinator, description) for description in SENSORS)
    async_add_entities(entities)


class RingPlusSensor(RingPlusEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    entity_description: RingPlusSensorDescription

    def __init__(self, coordinator: IntercomCoordinator, description: RingPlusSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator)


class LastOpenedSensor(RingPlusEntity, SensorEntity):
    """When the door was last opened, and how (attribute `source`, HA user in `user`). Survives restarts."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: IntercomCoordinator) -> None:
        super().__init__(coordinator, "last_opened")

    @property
    def native_value(self) -> Any:
        return self.coordinator.last_opened

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"source": self.coordinator.last_opened_source, "user": self.coordinator.last_opened_user}
