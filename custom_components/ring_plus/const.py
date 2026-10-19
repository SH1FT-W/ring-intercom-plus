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
