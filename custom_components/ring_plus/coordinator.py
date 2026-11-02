"""State per intercom: settings (polled) plus call/auto-unlock (event driven)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any, NamedTuple

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import IntercomApi
from .const import (
    ACTIVE_CALL_MAX_POLLS,
    ACTIVE_CALL_POLL,
    AUTO_UNLOCK_WINDOW,
    AUTO_UNLOCK_WINDOW_MAX,
    AUTO_UNLOCK_WINDOW_MIN,
    DING_HOLD,
    DOMAIN,
    EVENT_MAX_AGE,
    FALLBACK_MAX_AGE,
    ISSUE_PUSH_MISSING,
    KIND_INTERCOM_UNLOCK,
    MODE_RING,
    MODE_SCHEDULE,
    MODE_WINDOW,
    OPEN_SOURCES,
    OWN_UNLOCK_MATCH,
    PUSH_MATCH_WINDOW,
    PUSH_MISSING_AFTER,
    SETTINGS_INTERVAL,
    SOURCE_AUTO_UNLOCK,
    SOURCE_HOME_ASSISTANT,
    SOURCE_RING_APP,
    SOURCE_RING_HISTORY,
    SOURCE_UNKNOWN,
    UNLOCK_HOLD,
)
from .storage import PersistentState

_LOGGER = logging.getLogger(__name__)

# Before unloading, wait at most this long (seconds) for an opening that may already have reached Ring
OPEN_WAIT_ON_UNLOAD = 15


class RingAlert(NamedTuple):
    """An active alert of the Ring integration's push listener: Ring's own id and time of the event."""

    key: str
    created: datetime


AlertLookup = Callable[[str], RingAlert | None]


def _no_alert(_kind: str) -> RingAlert | None:
    return None


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
        state: PersistentState,
        schedule_entity_id: str | None = None,
        alert_lookup: AlertLookup = _no_alert,
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
        self.auto_unlock_mode: str | None = None  # MODE_RING or MODE_WINDOW while auto_unlock_until is set
        self._auto_unlock_timer: CALLBACK_TYPE | None = None
        self._saved = state.device(api.device_api_id)
        self._state = state
        window = self._saved.get("window_minutes")
        self.auto_unlock_window = (
            window
            if isinstance(window, int) and AUTO_UNLOCK_WINDOW_MIN <= window <= AUTO_UNLOCK_WINDOW_MAX
            else AUTO_UNLOCK_WINDOW_MIN
        )
        # Schedule: while it is on, every ring that arrives by push opens the door (unless switched off)
        self.schedule_entity_id = schedule_entity_id
        self._schedule_on = False
        self._suspended = False  # switched off during the current schedule period, until the schedule is off
        self._schedule_unsub: CALLBACK_TYPE | None = None
        self._open_task: asyncio.Task[None] | None = None
        self._open_sent = False
        # The Ring integration's event entities fire again for every event of the device while an alert is
        # active (about 3 minutes) and after its listener (re)starts. Only Ring's own alert id and time tell a
        # new ring apart, so auto-open and "last opened" go by those.
        self._alert = alert_lookup
        self._ding_key: str | None = None  # alert of the last ring seen (saved: a replay after a restart is old)
        self._unlock_key: str | None = None  # last unlock alert counted
        # "Last opened"
        self.last_opened: datetime | None = None
        self.last_opened_source: str | None = None
        self.last_opened_user: str | None = None
        self._restore()
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

    # ---------- Saved state ----------

    def _restore(self) -> None:
        """Values from before a restart or reload. Anything unreadable counts as "not set"."""
        now = dt_util.utcnow()
        until = _parse_time(self._saved.get("until"))
        mode = self._saved.get("mode", MODE_WINDOW)
        longest = {
            MODE_WINDOW: timedelta(minutes=AUTO_UNLOCK_WINDOW_MAX),
            MODE_RING: timedelta(seconds=AUTO_UNLOCK_WINDOW),
        }
        if until is not None and mode in longest and now < until <= now + longest[mode]:
            # The intercom's 60 s mode is restored too, so the switch does not show "off" while it is armed
            self.auto_unlock_until = until
            self.auto_unlock_mode = mode
        # A pause belongs to the schedule it was made for; another (or no) schedule drops it
        self._suspended = (
            self._saved.get("suspended") is True
            and self.schedule_entity_id is not None
            and self._saved.get("suspended_for") == self.schedule_entity_id
        )
        key = self._saved.get("ding_key")
        self._ding_key = key if isinstance(key, str) else None
        self.last_opened = _parse_time(self._saved.get("last_opened"))
        source = self._saved.get("last_opened_source")
        self.last_opened_source = source if source in OPEN_SOURCES and self.last_opened else None
        user = self._saved.get("last_opened_user")
        self.last_opened_user = user if isinstance(user, str) and self.last_opened else None

    @callback
    def _save(self) -> None:
        until = self.auto_unlock_until
        self._saved.update(
            {
                "window_minutes": self.auto_unlock_window,
                "until": until.isoformat() if until else None,
                "mode": self.auto_unlock_mode,
                "suspended": self._suspended,
                "suspended_for": self.schedule_entity_id if self._suspended else None,
                "ding_key": self._ding_key,
                "last_opened": self.last_opened.isoformat() if self.last_opened else None,
                "last_opened_source": self.last_opened_source,
                "last_opened_user": self.last_opened_user,
            }
        )
        self._state.async_save()

    @callback
    def async_start(self) -> None:
        """After setup: timer for a restored window, follow the schedule."""
        if self.auto_unlock_until is not None:
            delay = max((self.auto_unlock_until - dt_util.utcnow()).total_seconds(), 0)
            self._auto_unlock_timer = async_call_later(self.hass, delay, self._auto_unlock_expired)
        if self.schedule_entity_id:
            self._schedule_unsub = async_track_state_change_event(
                self.hass, [self.schedule_entity_id], self._schedule_event
            )
            self._schedule_changed(self.hass.states.get(self.schedule_entity_id))

    # ---------- Next ding unlocks ----------

    @property
    def _window_active(self) -> bool:
        return self.auto_unlock_until is not None and self.auto_unlock_until > dt_util.utcnow()

    @property
    def schedule_active(self) -> bool:
        return self._schedule_on and not self._suspended

    @property
    def auto_unlock_active(self) -> bool:
        return self._window_active or self.schedule_active

    @property
    def auto_unlock_active_mode(self) -> str | None:
        """What currently makes the next ring open the door (window wins over schedule)."""
        if self._window_active:
            return self.auto_unlock_mode
        return MODE_SCHEDULE if self.schedule_active else None

    async def async_set_auto_unlock_window(self, minutes: int) -> None:
        if not AUTO_UNLOCK_WINDOW_MIN <= minutes <= AUTO_UNLOCK_WINDOW_MAX:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="window_out_of_range",
                translation_placeholders={"min": str(AUTO_UNLOCK_WINDOW_MIN), "max": str(AUTO_UNLOCK_WINDOW_MAX)},
            )
        self.auto_unlock_window = minutes
        self._save()
        self.async_update_listeners()

    async def async_set_auto_unlock(self, enabled: bool, duration: timedelta | None = None) -> None:
        """Switch on (for `duration`, default the configured window) or off."""
        try:
            if enabled:
                await self._async_enable_auto_unlock(duration or timedelta(minutes=self.auto_unlock_window))
            else:
                await self._async_disable_auto_unlock()
        finally:
            # Also when Ring refused: what was changed here (e.g. the schedule pause) is saved and shown
            self._save()
            self.async_update_listeners()

    async def _async_enable_auto_unlock(self, duration: timedelta) -> None:
        if not timedelta(minutes=AUTO_UNLOCK_WINDOW_MIN) <= duration <= timedelta(minutes=AUTO_UNLOCK_WINDOW_MAX):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="window_out_of_range",
                translation_placeholders={"min": str(AUTO_UNLOCK_WINDOW_MIN), "max": str(AUTO_UNLOCK_WINDOW_MAX)},
            )
        if duration <= timedelta(seconds=AUTO_UNLOCK_WINDOW):
            # As before: the intercom itself opens on the next ring within 60 s
            if self.user_id is None:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_user_id")
            await self.api.async_set_auto_unlock(self.user_id, True, AUTO_UNLOCK_WINDOW)
            mode = MODE_RING
        else:
            if self._window_active and self.auto_unlock_mode == MODE_RING and self.user_id is not None:
                # Do not leave the intercom's own mode armed next to the longer window
                await self.api.async_set_auto_unlock(self.user_id, False, AUTO_UNLOCK_WINDOW)
            mode = MODE_WINDOW
        self._cancel_auto_unlock_timer()
        self.auto_unlock_mode = mode
        self.auto_unlock_until = dt_util.utcnow() + duration
        self._auto_unlock_timer = async_call_later(self.hass, duration.total_seconds(), self._auto_unlock_expired)
        # A schedule pause stays: switching on arms only this window, the schedule resumes once it was off

    async def _async_disable_auto_unlock(self) -> None:
        ring_armed = self._window_active and self.auto_unlock_mode == MODE_RING
        disarm_intercom = self.user_id is not None and (ring_armed or not self.auto_unlock_active)
        # Home Assistant's own part first, it needs no cloud: no opening pending, window off, schedule paused
        if self._open_task is not None and not self._open_task.done() and not self._open_sent:
            self._open_task.cancel()  # switched off right after a ring, before the command went out
        if self.schedule_active:
            # Off during a schedule period: pause until the schedule is seen "off" (saved, survives restarts).
            # Missed while Home Assistant was down, the pause simply lasts longer: the door stays closed.
            self._suspended = True
        if self.auto_unlock_mode == MODE_WINDOW:
            self._clear_window()
        if ring_armed and self.user_id is None:
            # Armed before a restart in which Ring did not return the user ID: cannot be disarmed, ends by itself
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_user_id")
        if disarm_intercom and self.user_id is not None:
            # Save Home Assistant's part before waiting for Ring: a reload or crash meanwhile must not lose a pause
            self._save()
            # The intercom's own mode: shown as armed until Ring confirms; an error is shown to the user
            await self.api.async_set_auto_unlock(self.user_id, False, AUTO_UNLOCK_WINDOW)
        self._clear_window()

    @callback
    def _clear_window(self) -> None:
        self._cancel_auto_unlock_timer()
        self.auto_unlock_until = None
        self.auto_unlock_mode = None

    @callback
    def _auto_unlock_expired(self, _now: datetime) -> None:
        self._auto_unlock_timer = None
        self.auto_unlock_until = None
        self.auto_unlock_mode = None
        self._save()
        self.async_update_listeners()

    def _cancel_auto_unlock_timer(self) -> None:
        if self._auto_unlock_timer:
            self._auto_unlock_timer()
            self._auto_unlock_timer = None

    # ---------- Schedule ----------

    @callback
    def _schedule_event(self, event: Event[EventStateChangedData]) -> None:
        self._schedule_changed(event.data["new_state"])

    @callback
    def _schedule_changed(self, state: State | None) -> None:
        """Schedule on = auto-unlock active; missing or unavailable counts as off for opening."""
        if self._suspended and state is not None and state.state == "off":
            # The paused period is over. Only a real "off" ends it: missing or unavailable (e.g. still loading
            # after a restart) must not lift a pause the user set.
            self._suspended = False
            self._save()
        self._schedule_on = state is not None and state.state == "on"
        self.async_update_listeners()

    # ---------- Auto-open by Home Assistant ----------

    @callback
    def _async_auto_open(self, alert: RingAlert | None) -> None:
        """A new ring arrived by push: open the door if Home Assistant's window or the schedule is active.

        Only for a ring Ring itself reports (alert) and as recent (Ring's time); never without an alert.
        """
        if alert is None:
            return
        mode = self.auto_unlock_active_mode
        if mode not in (MODE_WINDOW, MODE_SCHEDULE):
            return
        if abs(dt_util.utcnow() - alert.created) > EVENT_MAX_AGE:
            _LOGGER.warning("Auto-Öffnen %s: Klingeln zu alt, Tür bleibt zu", self.device_name)
            return
        if self._open_task is not None and not self._open_task.done():
            return  # the door is being opened already
        self._open_sent = False
        self._open_task = self.hass.async_create_task(self._async_open_for_ring(mode), eager_start=False)

    async def _async_open_for_ring(self, mode: str) -> None:
        self._open_sent = True  # from here on the command may reach Ring; switching off no longer cancels it
        try:
            await self.api.async_unlock_door()
        except Exception as err:  # noqa: BLE001 – logged; the window stays for the next ring
            _LOGGER.error("Auto-Öffnen %s: Tür nicht geöffnet: %s", self.device_name, err)
            return
        _LOGGER.info("Auto-Öffnen %s: Tür nach Klingeln geöffnet (%s)", self.device_name, mode)
        if mode == MODE_WINDOW and self.auto_unlock_mode == MODE_WINDOW:
            self._clear_window()  # "next ring": used up
        self._record_open(dt_util.utcnow(), SOURCE_AUTO_UNLOCK)
        self._show_unlocked()

    # ---------- Last opened ----------

    @callback
    def _record_open(self, when: datetime, source: str, user: str | None = None) -> None:
        self.last_opened = when
        self.last_opened_source = source
        self.last_opened_user = user
        self._save()
        self.async_update_listeners()

    def _own_open_near(self, when: datetime, window: timedelta) -> bool:
        return (
            self.last_opened is not None
            and self.last_opened_source in (SOURCE_HOME_ASSISTANT, SOURCE_AUTO_UNLOCK)
            and abs(when - self.last_opened) <= window
        )

    @callback
    def _history_unlock(self, created_at: datetime) -> None:
        """Ring's history lists an unlock: count it unless it is one already known."""
        if self.last_opened is not None and (
            created_at <= self.last_opened or abs(created_at - self.last_opened) <= PUSH_MATCH_WINDOW
        ):
            return
        self._record_open(created_at, SOURCE_RING_HISTORY)

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
    def _show_unlocked(self) -> None:
        """Show the door opener "unlocked" for 5 s."""
        if self._unlock_timer:
            self._unlock_timer()
        self.door_unlocked = True
        self._unlock_timer = async_call_later(self.hass, UNLOCK_HOLD, self._lock_again)
        self.async_update_listeners()

    @callback
    def async_handle_unlock(self) -> None:
        """Unlock event of the Ring integration (app, HA, other Ring clients): show it and note who opened."""
        alert = self._alert(KIND_INTERCOM_UNLOCK)
        if alert is not None and alert.key == self._unlock_key:
            return  # the Ring integration fired its unlock entity again for another event: no new unlock
        if alert is not None:
            self._unlock_key = alert.key
            when = alert.created
            if (self.last_opened is None or when > self.last_opened) and not self._own_open_near(
                when, OWN_UNLOCK_MATCH
            ):
                # Ring sends this push for unlocks from the app ("INTERCOM_UNLOCK_FROM_APP"); while the intercom's
                # own auto-unlock is armed it could also be that one, so the source stays unknown then
                ring_armed = self._window_active and self.auto_unlock_mode == MODE_RING
                self._record_open(when, SOURCE_UNKNOWN if ring_armed else SOURCE_RING_APP)
        self._show_unlocked()

    async def async_open_door(self, user: str | None = None) -> None:
        await self.api.async_unlock_door()
        self._record_open(dt_util.utcnow(), SOURCE_HOME_ASSISTANT, user)
        self._show_unlocked()

    @callback
    def async_handle_push_ding(self) -> None:
        """Ding via push from the Ring integration (immediate); if the fallback already had it, only note the push."""
        alert = self._alert("ding")
        if alert is not None:
            if alert.key == self._ding_key:
                # The Ring integration fires its ding entity again for any event of the device while the alert
                # lives (and when its listener starts): not a new ring
                return
            self._ding_key = alert.key
            self._save()
        now = dt_util.utcnow()
        self._last_push_ding = now
        self._push_recovered()
        if self._last_fallback_ding is not None and now - self._last_fallback_ding <= PUSH_MATCH_WINDOW:
            return
        self._async_auto_open(alert)
        self.async_handle_ding()

    @callback
    def async_handle_activity(self, category: str | None, created_at: datetime | None) -> None:
        """Ring integration's "last activity" changed: catch up on a ding without push (about 1 minute later)."""
        if category == KIND_INTERCOM_UNLOCK and created_at is not None:
            self._history_unlock(created_at)
            return
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
        if self.auto_unlock_until is not None and self.auto_unlock_mode == MODE_RING:
            # The intercom's own mode is used up by any ring (as before). Home Assistant's window only ends
            # when Home Assistant actually opened the door (see _async_open_for_ring).
            self._clear_window()
            self._save()
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

    async def async_wait_for_open(self) -> None:
        """Before unloading: let an opening that may already have reached Ring finish (bounded)."""
        task = self._open_task
        if task is not None and not task.done() and self._open_sent:
            await asyncio.wait({task}, timeout=OPEN_WAIT_ON_UNLOAD)
            if not task.done() and self.auto_unlock_mode == MODE_WINDOW:
                # Still pending: the door may open, so the window counts as used. The reloaded entry restores
                # from the saved state and must not open again on the next ring.
                self._clear_window()
                self._save()

    @callback
    def async_shutdown_timers(self) -> None:
        self._cancel_auto_unlock_timer()
        if self._schedule_unsub:
            self._schedule_unsub()
            self._schedule_unsub = None
        if self._open_task is not None and not self._open_task.done() and not self._open_sent:
            self._open_task.cancel()
        self._cancel_call_timer()
        if self._call_task is not None and not self._call_task.done():
            self._call_task.cancel()
        self._call_task = None
        for cancel in (self._ding_timer, self._unlock_timer):
            if cancel:
                cancel()
        self._ding_timer = self._unlock_timer = None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    parsed = dt_util.parse_datetime(value)
    return dt_util.as_utc(parsed) if parsed is not None and parsed.tzinfo is not None else None
