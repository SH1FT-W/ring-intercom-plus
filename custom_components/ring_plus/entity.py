"""Basis: Entitäten hängen am vorhandenen Gerät der HA-Ring-Integration."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IntercomCoordinator


class RingPlusEntity(CoordinatorEntity[IntercomCoordinator]):
    """Gemeinsamer Unterbau."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IntercomCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.api.device_api_id}-{key}"
        # Seit HA 2026.9 gelten Gerätekennungen nur je Integration → per device_entry ans vorhandene
        # Ring-Gerät hängen (wie HA-Helfer), statt mit device_info ein zweites Gerät anzulegen
        self.device_entry = coordinator.device_entry

    async def _run[T](self, call: Awaitable[T]) -> T:
        """Befehl ausführen; jeder Fehler der Ring-Cloud wird eine übersetzte Meldung in der Oberfläche."""
        try:
            return await call
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
