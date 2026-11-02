"""State per intercom: settings (polled) plus call/auto-unlock (event driven)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import IntercomApi
from .const import (
    ACTIVE_CALL_MAX_POLLS,
    ACTIVE_CALL_POLL,
    AUTO_UNLOCK_WINDOW,
    DING_HOLD,
    DOMAIN,
    FALLBACK_MAX_AGE,
    ISSUE_PUSH_MISSING,
    PUSH_MATCH_WINDOW,
    PUSH_MISSING_AFTER,
    SETTINGS_INTERVAL,
    UNLOCK_HOLD,
)

_LOGGER = logging.getLogger(__name__)


class IntercomCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """One Ring Intercom. `data` = intercom_settings from the cloud."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: IntercomApi,
        *,
        ring_device_id: str,
        name: str,
        user_id: str | None,
        device_entry: dr.DeviceEntry | None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {name}",
            update_interval=SETTINGS_INTERVAL,
        )
        self.api = api
        self.ring_device_id = ring_device_id  # MAC, device identifier of the HA Ring integration
        self.device_name = name
        self.user_id = user_id
        self.device_entry = device_entry  # device of the HA Ring integration
        self.hw_revision: str | None = None
        self.active_call: bool | None = None
        self.auto_unlock_until: datetime | None = None
        self._auto_unlock_timer: CALLBACK_TYPE | None = None
        self._call_timer: CALLBACK_TYPE | None = None
        self._call_task: asyncio.Task[None] | None = None
        self._call_polls = 0
        self.ding: bool = False
        self.door_unlocked: bool = False
        self._ding_timer: CALLBACK_TYPE | None = None
        self._unlock_timer: CALLBACK_TYPE | None = None
        # Fallback without push: last ding seen in "last activity", and the last ding per path
        self._activity_seen: datetime | None = None
        self._last_push_ding: datetime | None = None
        self._last_fallback_ding: datetime | None = None
        self.push_misses = 0

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.async_get_intercom_settings()
        except Exception as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="settings_unreadable",
                translation_placeholders={"error": str(err) or type(err).__name__},
            ) from err

    async def async_load_hw_revision(self) -> None:
        """Once at startup; an error here blocks nothing."""
        try:
            self.hw_revision = await self.api.async_hw_revision()
        except Exception as err:  # noqa: BLE001 – diagnostic value, may be missing
            _LOGGER.debug("Hardware-Revision von %s nicht lesbar: %s", self.device_name, err)

    # ---------- Next ding unlocks ----------

    @property
    def auto_unlock_active(self) -> bool:
        return self.auto_unlock_until is not None and self.auto_unlock_until > dt_util.utcnow()

    async def async_set_auto_unlock(self, enabled: bool) -> None:
        if self.user_id is None:
            raise RuntimeError("Ring-Benutzer-ID unbekannt")
        await self.api.async_set_auto_unlock(self.user_id, enabled, AUTO_UNLOCK_WINDOW)
        self._cancel_auto_unlock_timer()
        if enabled:
            self.auto_unlock_until = dt_util.utcnow() + timedelta(seconds=AUTO_UNLOCK_WINDOW)
            self._auto_unlock_timer = async_call_later(self.hass, AUTO_UNLOCK_WINDOW, self._auto_unlock_expired)
        else:
            self.auto_unlock_until = None
        self.async_update_listeners()

    @callback
    def _auto_unlock_expired(self, _now: datetime) -> None:
        self._auto_unlock_timer = None
        self.auto_unlock_until = None
        self.async_update_listeners()

    def _cancel_auto_unlock_timer(self) -> None:
        if self._auto_unlock_timer:
            self._auto_unlock_timer()
            self._auto_unlock_timer = None

    # ---------- Ding / door opener (briefly "on", like ring-mqtt) ----------

    @callback
    def _ding_off(self, _now: datetime) -> None:
        self._ding_timer = None
        self.ding = False
        self.async_update_listeners()

    @callback
    def _lock_again(self, _now: datetime) -> None:
        self._unlock_timer = None
        self.door_unlocked = False
        self.async_update_listeners()

    @callback
    def async_handle_unlock(self) -> None:
        """Door was opened (app, HA, auto-unlock): show the door opener "unlocked" for 5 s."""
        if self._unlock_timer:
            self._unlock_timer()
        self.door_unlocked = True
        self._unlock_timer = async_call_later(self.hass, UNLOCK_HOLD, self._lock_again)
        self.async_update_listeners()

    async def async_open_door(self) -> None:
        await self.api.async_unlock_door()
        self.async_handle_unlock()

    @callback
    def async_handle_push_ding(self) -> None:
        """Ding via push from the Ring integration (immediate); if the fallback already had it, only note the push."""
        now = dt_util.utcnow()
        self._last_push_ding = now
        self._push_recovered()
        if self._last_fallback_ding is not None and now - self._last_fallback_ding <= PUSH_MATCH_WINDOW:
            return
        self.async_handle_ding()

    @callback
    def async_handle_activity(self, category: str | None, created_at: datetime | None) -> None:
        """Ring integration's "last activity" changed: catch up on a ding without push (about 1 minute later)."""
        if category != "ding" or created_at is None:
            return
        if self._activity_seen is not None and created_at <= self._activity_seen:
            return
        self._activity_seen = created_at
        now = dt_util.utcnow()
        if now - created_at > FALLBACK_MAX_AGE:
            return  # old entry, e.g. right after a restart
        if self._last_push_ding is not None and abs(self._last_push_ding - created_at) <= PUSH_MATCH_WINDOW:
            return  # already came via push
        _LOGGER.info("Klingeln von %s ohne Push erkannt (über Letzte Aktivität)", self.device_name)
        self._last_fallback_ding = now
        self.push_misses += 1
        if self.push_misses >= PUSH_MISSING_AFTER:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{ISSUE_PUSH_MISSING}_{self.ring_device_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_PUSH_MISSING,
                translation_placeholders={"name": self.device_name},
            )
        self.async_handle_ding()

    @callback
    def _push_recovered(self) -> None:
        if self.push_misses:
            self.push_misses = 0
            ir.async_delete_issue(self.hass, DOMAIN, f"{ISSUE_PUSH_MISSING}_{self.ring_device_id}")

    @callback
    def async_handle_ding(self) -> None:
        """It rang: ding sensor on, auto-unlock used up, poll the call state until the call ends."""
        if self._ding_timer:
            self._ding_timer()
        self.ding = True
        self._ding_timer = async_call_later(self.hass, DING_HOLD, self._ding_off)
        if self.auto_unlock_until is not None:
            self._cancel_auto_unlock_timer()
            self.auto_unlock_until = None
        self.async_update_listeners()
        # New polling chain; a request still running is cancelled, otherwise two chains would run in parallel
        self._call_polls = 0
        self._cancel_call_timer()
        self._start_call_poll()

    # ---------- Call active ----------

    @callback
    def _start_call_poll(self) -> None:
        if self._call_task is not None and not self._call_task.done():
            self._call_task.cancel()
        self._call_task = self.config_entry.async_create_background_task(
            self.hass, self._async_poll_active_call(), f"{DOMAIN} active_call {self.device_name}"
        )

    async def _async_poll_active_call(self) -> None:
        active: bool | None
        try:
            active = await self.api.async_active_call()
        except Exception as err:  # noqa: BLE001 – a cloud hiccup must not stop the polling
            _LOGGER.debug("active_call von %s fehlgeschlagen: %s", self.device_name, err)
            active = None  # unknown, not "no call": keep the last known state and ask again
        self._call_polls += 1
        if active is not None and active != self.active_call:
            self.active_call = active
            self.async_update_listeners()
        if active is not False and self._call_polls < ACTIVE_CALL_MAX_POLLS:
            self._call_timer = async_call_later(self.hass, ACTIVE_CALL_POLL, self._call_timer_fired)

    @callback
    def _call_timer_fired(self, _now: datetime) -> None:
        self._call_timer = None
        self._start_call_poll()

    def _cancel_call_timer(self) -> None:
        if self._call_timer:
            self._call_timer()
            self._call_timer = None

    @callback
    def async_shutdown_timers(self) -> None:
        self._cancel_auto_unlock_timer()
        self._cancel_call_timer()
        if self._call_task is not None and not self._call_task.done():
            self._call_task.cancel()
        self._call_task = None
        for cancel in (self._ding_timer, self._unlock_timer):
            if cancel:
                cancel()
        self._ding_timer = self._unlock_timer = None
