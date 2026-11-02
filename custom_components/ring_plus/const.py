"""Konstanten für Ring Intercom Plus."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ring_plus"
RING_DOMAIN: Final = "ring"

# Optionen: PIN fürs Aufschließen (leer = keine; dann öffnet jeder Aufruf von lock.unlock die Tür)
CONF_UNLOCK_CODE: Final = "unlock_code"
CODE_FORMAT: Final = r"^\d{4,8}$"

# Gerätearten der Ring Intercom (wie python-ring-doorbell INTERCOM_KINDS)
INTERCOM_KINDS: Final = ("intercom_handset_audio", "intercom_handset_video")

# Einstellungen ändern sich selten – alle 5 Minuten nachlesen, nach einer Änderung sofort
SETTINGS_INTERVAL: Final = timedelta(minutes=5)

# „Nächstes Klingeln öffnet“: die App schickt immer 60 Sekunden
AUTO_UNLOCK_WINDOW: Final = 60

# Time window for "Next ring opens", in minutes. 1 = the intercom's own 60 s mode (default, as before);
# longer windows are handled by Home Assistant: it opens the door itself when the ring arrives by push.
CONF_AUTO_UNLOCK_SCHEDULE: Final = "auto_unlock_schedule"
AUTO_UNLOCK_WINDOW_MIN: Final = 1
AUTO_UNLOCK_WINDOW_MAX: Final = 480  # 8 hours: never open-ended without a schedule
MODE_RING: Final = "ring"  # intercom's own mode (set_autounlock_mode, 60 s)
MODE_WINDOW: Final = "window"  # Home Assistant opens on the next ring within the window
MODE_SCHEDULE: Final = "schedule"  # Home Assistant opens on every ring while the schedule is on
# Only a ring this recent (Ring's own time of the alert) opens the door
EVENT_MAX_AGE: Final = timedelta(seconds=30)
SERVICE_NEXT_RING_OPENS: Final = "next_ring_opens"
ATTR_DURATION: Final = "duration"

# "Last opened": who or what opened the door
SOURCE_HOME_ASSISTANT: Final = "home_assistant"
SOURCE_AUTO_UNLOCK: Final = "auto_unlock"
SOURCE_RING_APP: Final = "ring_app"
SOURCE_RING_HISTORY: Final = "ring_history"
SOURCE_UNKNOWN: Final = "unknown"
OPEN_SOURCES: Final = (SOURCE_HOME_ASSISTANT, SOURCE_AUTO_UNLOCK, SOURCE_RING_APP, SOURCE_RING_HISTORY, SOURCE_UNKNOWN)
# Own unlock and the unlock push Ring sends for it = the same opening
OWN_UNLOCK_MATCH: Final = timedelta(seconds=30)
# Ring history kind for an unlock (ring_doorbell RingEventKind.INTERCOM_UNLOCK)
KIND_INTERCOM_UNLOCK: Final = "intercom_unlock"

# Öffnungsdauer: App erlaubt 1–10 s, Vorgabe 3 s
UNLOCK_DURATION_MIN: Final = 1
UNLOCK_DURATION_MAX: Final = 10
UNLOCK_DURATION_DEFAULT: Final = 3

# Nach einem Klingeln: so oft „Anruf aktiv“ nachfragen, bis der Anruf vorbei ist
ACTIVE_CALL_POLL: Final = timedelta(seconds=10)
ACTIVE_CALL_MAX_POLLS: Final = 18  # 3 Minuten

# Wie ring-mqtt: Klingel-Sensor 20 s an, Türöffner 5 s „aufgeschlossen“
DING_HOLD: Final = 20
UNLOCK_HOLD: Final = 5

# Ersatzweg, wenn der Push der Ring-Integration ausfällt: Klingeln aus „Letzte Aktivität“ (Abfrage, ~1 Min später)
FALLBACK_MAX_AGE: Final = timedelta(minutes=3)  # ältere Einträge (z. B. nach einem Neustart) zählen nicht
PUSH_MATCH_WINDOW: Final = timedelta(minutes=2)  # Push und Abfrage innerhalb dieses Fensters = dasselbe Klingeln
PUSH_MISSING_AFTER: Final = 2  # so oft hintereinander nur über den Ersatzweg → Reparatur-Hinweis
ISSUE_PUSH_MISSING: Final = "push_missing"
