"""Ring-Cloud-Aufrufe für die Intercom, die HA-ring und ring-mqtt nicht kennen.

Formate stammen aus der Ring-Android-App 3.111.1 (GuestAccessRepositoryImpl,
UnlockDurationSettingsRepositoryImpl, RingToOpenSettingsRepositoryImpl,
IntercomActiveSessionServiceImpl, DeviceHealthRepositoryImpl). Ohne HA-Abhängigkeit, damit testbar.
Die Anmeldung kommt von der HA-Ring-Integration: `query` ist deren `Ring.async_query`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import copy
import json
import time
from typing import Any, Protocol
import uuid


class RingResponse(Protocol):
    """Antwort von `Ring.async_query` (ring_doorbell.Auth.Response)."""

    def json(self) -> Any:
        """Antwort als JSON."""


Query = Callable[..., Awaitable[RingResponse]]

SETTINGS_URL = "/devices/v1/devices/{0}/settings"
RPC_URL = "/commands/v1/devices/{0}/device_rpc"
COMMAND_URL = "/commands/v1/devices/{0}"
PROFILE_URL = "/clients_api/profile"


class IntercomCommandError(Exception):
    """Die Intercom hat einen Befehl abgelehnt oder nicht beantwortet."""


def _now_ms() -> int:
    return int(time.time() * 1000)


def parse_config(intercom_settings: dict[str, Any]) -> dict[str, Any]:
    """`intercom_settings.config` ist ein JSON-Text im JSON – auspacken."""
    raw = intercom_settings.get("config")
    if not raw:
        return {}
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def unlock_duration(intercom_settings: dict[str, Any]) -> int | None:
    """Öffnungsdauer in Sekunden; None, wenn die Anlage nicht analog ist (App zeigt die Einstellung dann nicht)."""
    analog = parse_config(intercom_settings).get("analog")
    if not isinstance(analog, dict):
        return None
    millis = analog.get("unlock_duration")
    if millis is None:
        return 3  # App-Vorgabe
    try:
        return max(1, min(10, int(millis) // 1000))
    except (TypeError, ValueError):
        return None  # unlesbarer Wert: lieber „unbekannt“ als ein Absturz der Entität


class IntercomApi:
    """Befehle und Einstellungen einer Ring Intercom."""

    def __init__(self, query: Query, device_api_id: int) -> None:
        self._query = query
        self.device_api_id = device_api_id

    async def async_get_intercom_settings(self) -> dict[str, Any]:
        """Aktuelle `intercom_settings` (ring_to_open, unlock_mode, config …)."""
        resp = await self._query(SETTINGS_URL.format(self.device_api_id), method="GET")
        settings = resp.json().get("intercom_settings")
        if not isinstance(settings, dict):
            raise IntercomCommandError("Antwort enthält keine intercom_settings")
        return settings

    async def _async_patch_intercom_settings(self, settings: dict[str, Any]) -> None:
        # Wie die App: das komplette Objekt zurückschicken, nur ein Feld geändert (Gson lässt null weg)
        body = {key: value for key, value in settings.items() if value is not None}
        await self._query(SETTINGS_URL.format(self.device_api_id), method="PATCH", json={"intercom_settings": body})

    async def async_set_ring_to_open(self, current: dict[str, Any], enabled: bool) -> dict[str, Any]:
        """„Ring-to-Open“ (an) oder „Direkt öffnen“ (aus)."""
        settings = copy.deepcopy(current)
        settings["ring_to_open"] = enabled
        await self._async_patch_intercom_settings(settings)
        return settings

    async def async_set_unlock_duration(self, current: dict[str, Any], seconds: int) -> dict[str, Any]:
        """Wie lange der Türöffner betätigt wird (1–10 s, gespeichert in Millisekunden)."""
        config = parse_config(current)
        analog = config.get("analog")
        if not isinstance(analog, dict):
            raise IntercomCommandError("Öffnungsdauer gibt es nur bei analogen Anlagen")
        analog["unlock_duration"] = int(seconds) * 1000
        settings = copy.deepcopy(current)
        settings["config"] = json.dumps(config, separators=(",", ":"))
        await self._async_patch_intercom_settings(settings)
        return settings

    async def async_rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """JSON-RPC an die Intercom; liefert `result`, wirft bei Fehler oder code != 0."""
        payload = {
            "command_name": "device_rpc",
            "request": {"id": str(uuid.uuid4()), "jsonrpc": "2.0", "method": method, "params": params},
        }
        resp = await self._query(RPC_URL.format(self.device_api_id), method="PUT", json=payload)
        data = resp.json() or {}
        if error := data.get("error"):
            raise IntercomCommandError(f"{method}: {error}")
        result = data.get("result")
        if not isinstance(result, dict):
            raise IntercomCommandError(f"{method}: keine Antwort")
        code = result.get("code")
        if code not in (0, None):
            raise IntercomCommandError(f"{method}: code {code}")
        return result

    async def async_set_auto_unlock(self, user_id: str, enabled: bool, waiting_interval: int) -> None:
        """Nächstes Klingeln innerhalb von `waiting_interval` Sekunden öffnet die Tür (Gast/Lieferung)."""
        await self.async_rpc(
            "set_autounlock_mode",
            {
                "user_id": user_id,
                "issue_time": _now_ms(),
                "enabled": enabled,
                "waiting_interval": waiting_interval if enabled else 0,
                "anyring": 0,
                "origin": "user",
            },
        )

    async def async_active_call(self) -> bool:
        """Läuft gerade ein Gespräch an der Intercom?"""
        result = await self.async_rpc("active_call", {"command_timeout": 5, "issue_time": _now_ms()})
        return bool(result.get("active_call"))

    async def async_hw_revision(self) -> str | None:
        """Hardware-Revision der Intercom."""
        result = await self.async_rpc(
            "get_hw_revision", {"timeout": 3600, "command_timeout": 2, "issue_time": _now_ms()}
        )
        value = result.get("hw_revision")
        return str(value) if value not in (None, "") else None

    async def async_unlock_door(self) -> None:
        """Tür öffnen – gleiches Format wie python-ring-doorbell (HA-Knopf „Tür öffnen“)."""
        await self.async_rpc("unlock_door", {"door_id": 0, "user_id": -1})

    async def async_reboot(self) -> None:
        """Intercom neu starten (gleicher Befehl wie „Gerät neu starten“ in der App)."""
        await self._query(COMMAND_URL.format(self.device_api_id), method="PATCH", json={"command_name": "reboot"})


async def async_get_user_id(query: Query) -> str | None:
    """Ring-Benutzer-ID des angemeldeten Kontos (für set_autounlock_mode)."""
    resp = await query(PROFILE_URL, method="GET")
    profile = (resp.json() or {}).get("profile") or {}
    user_id = profile.get("id")
    return str(user_id) if user_id is not None else None
