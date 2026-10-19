"""Nachgebaute Ring-Cloud + HA-Ring-Eintrag für die Tests."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from typing import Any

DEVICE_API_ID = 123456
MAC = "aa:bb:cc:dd:ee:ff"
USER_ID = 98765

INTERCOM_SETTINGS: dict[str, Any] = {
    "config": json.dumps({"analog": {"unlock_duration": 3000, "audio_amp": 2}, "intercom_type": "analog"}),
    "intercom_type": "analog",
    "mic_index": None,
    "predecessor": "{}",
    "ring_to_open": False,
    "speaker_index": None,
    "unlock_mode": 0,
}


class FakeResponse:
    def __init__(self, data: Any) -> None:
        self._data = data

    def json(self) -> Any:
        return self._data


class FakeRing:
    """Ersetzt ring_doorbell.Ring.async_query; merkt sich alle Aufrufe."""

    def __init__(self) -> None:
        self.settings = copy.deepcopy(INTERCOM_SETTINGS)
        self.calls: list[tuple[str, str, Any]] = []
        self.active_call = [True, False]  # erste Abfrage: Gespräch läuft, danach vorbei
        self.rpc_error: dict[str, Any] | None = None
        self.active_call_error = False  # active_call schlägt fehl (Cloud-Hänger)
        self.profile: dict[str, Any] | None = {"id": USER_ID}
        self.profile_error = False

    async def async_query(self, url: str, method: str = "GET", json: Any = None, **_: Any) -> FakeResponse:
        self.calls.append((method, url, copy.deepcopy(json)))
        if url == "/clients_api/profile":
            if self.profile_error:
                raise RuntimeError("Profil nicht lesbar")
            return FakeResponse({"profile": self.profile})
        if url == f"/devices/v1/devices/{DEVICE_API_ID}/settings":
            if method == "PATCH":
                self.settings.update(json["intercom_settings"])
            return FakeResponse({"intercom_settings": copy.deepcopy(self.settings), "volume_settings": {}})
        if url == f"/commands/v1/devices/{DEVICE_API_ID}/device_rpc":
            if self.rpc_error:
                return FakeResponse({"error": self.rpc_error})
            rpc = json["request"]["method"]
            result: dict[str, Any] = {"code": 0}
            if rpc == "active_call" and self.active_call_error:
                raise RuntimeError("Cloud hängt")
            if rpc == "active_call":
                result["active_call"] = self.active_call.pop(0) if self.active_call else False
            if rpc == "get_hw_revision":
                result["hw_revision"] = "RS-2"
            return FakeResponse({"id": json["request"]["id"], "jsonrpc": "2.0", "result": result})
        if url == f"/commands/v1/devices/{DEVICE_API_ID}":
            return FakeResponse({})
        raise AssertionError(f"unerwartete URL {method} {url}")

    def rpcs(self, name: str) -> list[dict[str, Any]]:
        return [
            call[2]["request"]["params"]
            for call in self.calls
            if call[1].endswith("/device_rpc") and call[2]["request"]["method"] == name
        ]


def fake_intercom() -> SimpleNamespace:
    return SimpleNamespace(
        id=DEVICE_API_ID, device_api_id=DEVICE_API_ID, device_id=MAC, name="Front Door", kind="intercom_handset_audio"
    )
