# Changelog

## 26.11.2 – 02.11.2026

- **Next ring opens with a time window:** new number "Next ring opens: time window" (1 to 480 minutes) and action `ring_plus.next_ring_opens` with an optional `duration`. 1 minute stays the default and works as before (the intercom's own 60 seconds). Longer windows are handled by Home Assistant: it opens the door when the next ring arrives by push, then the switch turns off. A ring seen only later through "Last activity" never opens the door. The window survives restarts and is never longer than 8 hours.
- **Schedule for Next ring opens (optional):** pick a schedule helper in the options. While it is on, every ring that arrives by push opens the door. Switching "Next ring opens" off pauses the schedule until it turns off, also across restarts.
- **Last opened:** new sensor with the time of the last opening and its source (`home_assistant` with the user, `auto_unlock`, `ring_app`, `ring_history`, `unknown`). It survives restarts.
- The options now start with a menu (PIN, schedule); changing one keeps the other.
- The switch "Next ring opens" stays available while the intercom settings cannot be read, and it now exists even if Ring does not return the user ID of the account (then only the 1 minute mode is missing), so it can always be switched off.
- The intercom's own 60 seconds survive a reload of Ring Intercom Plus: the switch keeps showing them and switching off still disarms the intercom.
- Home Assistant opens only for a new ring as Ring identifies it (its own id and time), not when the Ring integration repeats an earlier ring event, for example after an unlock or a restart.
- **Fix:** a reload of the Ring integration no longer counts as a ring or an unlock (its event entities come back with their old state); before, the ding sensor and the door opener briefly switched on. A ring event that the Ring integration repeats while the ring is still active (for example on the next unlock) no longer counts as a second ring.
- Tests: time window, schedule, restarts, repeated and old ring events (also against the real Ring integration of Home Assistant).

## 26.11.1 – 02.11.2026

- **Fix:** a cloud error while checking "Call active" no longer switches the sensor off during a call. The last known state is kept and checking continues until the usual limit.
- Tests: Ring Intercom Plus now also runs against the real Ring integration of Home Assistant, so a change there that breaks it shows up in the tests.

## 26.10.3 – 19.10.2026

- **Rings without push:** if the official Ring integration stops receiving its instant push messages (a known problem), Ring Intercom Plus now still detects a ring from the integration's regular "Last activity" check, about a minute later. A ring that arrives by push is never counted twice.
- **Repair issue:** after two rings in a row that only arrived through this fallback, Home Assistant shows a repair issue suggesting to reload or reconfigure the Ring integration. It disappears with the next ring that arrives by push.

## 26.10.2 – 19.10.2026

- **Fix:** A ring while the "Call active" polling is still running no longer starts a second polling chain.
- PIN comparison in constant time; an unreadable unlock duration value makes the entity "unknown" instead of
  crashing it.
- Errors while reading the settings are translated; a ring updates the entities only once.
- Tests: second ring during polling, settings errors, unreadable unlock duration.
- **Security:** Optional PIN for the door opener (Configure). With a PIN, `lock.unlock` opens only with the right
  code; the default stays without a PIN as before. The README clearly warns that voice assistants, dashboards and
  automations can open the real door.
- **Fix:** If the ding or unlock event entity of the Ring integration is renamed (or only shows up later), Ring Intercom Plus
  keeps listening; before, the handlers were bound to the old entity ID.
- **Fix:** If the Ring integration reloads or is removed, Ring Intercom Plus reloads too; before, its entities stayed
  "unavailable" with the old Ring object.
- The attribute of the switch "Next ring opens" is called `until` (translated) instead of `bis`.
- Error wrapper once in `entity.py` instead of copied five times; mypy strict; docstrings without installation
  specific entity IDs.
- New: `hacs.json`, `LICENSE`, `quality_scale.yaml` (honest: silver, gold with gaps). README with setup, options,
  removal and troubleshooting.
- Tooling: GitHub checks (ruff, mypy, translations, pytest with coverage limit, hassfest, weekly against the newest
  Home Assistant), `tools/pruefe-uebersetzungen.py`, `tools/next-version` from the shared template; template leftovers
  (ruff `dev/**`, mypy astral, pytest markers) removed.

## 26.10.1 – 16.10.2026

- **New version scheme:** From now on the version counts **year.month.release of the month**: `26.10.1` is the first
  release in October 2026, the next month starts at `.1` again (for example `26.11.1`). The jump from `1.0.2` to
  `26.10.1` is intended: Home Assistant and update tools see `26.10.1` as newer.

## 1.0.2 – 13.10.2026

- New icon: Ring logo with a "+" badge.

## 1.0.1 – 12.10.2026

- Own icon (intercom with plus) for the integrations page.

## 1.0.0 – 12.10.2026

First version: door opener (lock), ding, call active, next ring opens, unlock duration, Ring-to-Open, restart,
diagnostic sensors. Can replace the intercom functions of ring-mqtt.
