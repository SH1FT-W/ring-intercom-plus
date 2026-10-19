# Changelog

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
