"""Diagnose-Sensoren: Hardware-Revision, Anlagentyp, Entsperr-Modus."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
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
    async_add_entities(
        RingPlusSensor(coordinator, description)
        for coordinator in entry.runtime_data.intercoms
        for description in SENSORS
    )


class RingPlusSensor(RingPlusEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    entity_description: RingPlusSensorDescription

    def __init__(self, coordinator: IntercomCoordinator, description: RingPlusSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator)
