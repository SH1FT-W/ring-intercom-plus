"""Türöffner als Schloss.

Normal „verriegelt“; Aufschließen öffnet die Tür und zeigt 5 s „aufgeschlossen“. Auch Öffnungen aus der
Ring-App oder per Auto-Öffnen erscheinen kurz als aufgeschlossen. Optional verlangt das Aufschließen eine PIN
(Optionen), damit Sprachassistent, Dashboard oder Automationen die Tür nicht ohne Code öffnen können.
"""

from __future__ import annotations

import hmac
from typing import Any

from homeassistant.components.lock import ATTR_CODE, LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RingPlusConfigEntry
from .const import CODE_FORMAT, CONF_UNLOCK_CODE, DOMAIN
from .coordinator import IntercomCoordinator
from .entity import RingPlusEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: RingPlusConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    code = str(entry.options.get(CONF_UNLOCK_CODE) or "")
    async_add_entities(DoorLock(coordinator, code) for coordinator in entry.runtime_data.intercoms)


class DoorLock(RingPlusEntity, LockEntity):
    def __init__(self, coordinator: IntercomCoordinator, code: str) -> None:
        super().__init__(coordinator, "door")
        self._code = code
        # Ohne PIN bleibt alles wie bisher (kein Code-Feld); mit PIN prüft HA das Format, wir den Wert
        self._attr_code_format = CODE_FORMAT if code else None

    @property
    def is_locked(self) -> bool:
        return not self.coordinator.door_unlocked

    async def async_unlock(self, **kwargs: Any) -> None:
        # Vergleich in konstanter Zeit, damit die Antwortzeit nichts über die PIN verrät
        if self._code and not hmac.compare_digest(str(kwargs.get(ATTR_CODE) or ""), self._code):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="wrong_code")
        await self._run(self.coordinator.async_open_door())

    async def async_lock(self, **kwargs: Any) -> None:
        # Die Intercom „verriegelt“ von selbst; nichts zu senden
        return
