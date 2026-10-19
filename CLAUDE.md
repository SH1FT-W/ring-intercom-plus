# Ring Intercom Plus – Projektregeln

HA-Integration (`custom_components/ring_plus`, Domain `ring_plus`) mit Zusatzfunktionen für die **Ring Intercom**
(Türöffner, Klingel, Anruf aktiv, Nächstes Klingeln öffnet, Öffnungsdauer, Ring-to-Open, Neustart, Diagnose).
Ergänzt die offizielle HA-Integration `ring` und nutzt deren Anmeldung; kann die Intercom-Funktionen von ring-mqtt
ersetzen. An echter Hardware geprüft: Ring Intercom (Audio).

- Repo wird **öffentlich**: nichts Persönliches ins Repo (keine Namen, echten Entity-IDs, Geräte-/Profil-IDs,
  Seriennummern, Heimnetz-Details, lokalen Pfade). Testdaten bleiben fiktiv.
- README, CHANGELOG, Release-Notizen, Issue-Texte und Commit-Texte auf Englisch.
- Lokal committen ok, Push und Releases nur nach Rückfrage.
- **Keine echten Geräte ansteuern:** Öffnen-Befehle öffnen eine echte Tür. Live-Tests nur mit dem Besitzer.

## Aufbau

- Keine eigene Anmeldung: `__init__.py` holt sich bei jedem Aufruf `runtime_data.api.async_query` des geladenen
  `ring`-Eintrags (ring_doorbell). Ändert HA den Aufbau (`runtime_data.api` / `.devices.all_devices`), bleibt Ring Intercom Plus
  in „Wird erneut versucht“ mit Meldung im Log.
- Entitäten hängen per `entity.device_entry` am Gerät der Ring-Integration (seit HA 2026.9 gelten Gerätekennungen
  nur je Integration, `device_info` würde ein zweites Gerät anlegen).
- Klingeln/Entsperren kommen aus den Event-Entitäten von `ring` (unique_id `<api_id>-ding` / `-intercom_unlock`),
  keine zweite Push-Verbindung. Die Handler werden über Registry-Ereignisse neu aufgesetzt (Umbenennung, späteres
  Auftauchen); `SIGNAL_CONFIG_ENTRY_CHANGED` des `ring`-Eintrags (Wechsel nach LOADED oder REMOVED) lädt Ring Intercom Plus neu.
- Optionen: `unlock_code` (PIN 4 bis 8 Ziffern, `CODE_FORMAT`); gesetzt → `lock` zeigt `code_format`, HA prüft Format,
  `async_unlock` den Wert (konstante Zeit). Standard ohne PIN (dann öffnen auch Dashboards/Automationen ohne Code).
  Optionsänderung = Reload.
- Fehler-Wrapper `_run` in `entity.py`, nicht je Plattform kopieren.
- `api.py` ohne HA, testbar. Einstellungen alle 5 Min (`GET devices/v1/devices/<id>/settings`), nach Änderung sofort.
- Wer von ring-mqtt kommt, kann die neuen Entitäten auf die alten Entity-IDs umbenennen; Automationen und Dashboards
  laufen dann weiter. Ring Intercom Plus selbst setzt keine festen Entity-IDs voraus.

## Protokoll (aus der Ring-Android-App 3.111.1)

- RPC: `PUT /commands/v1/devices/<id>/device_rpc`, Body `{"command_name":"device_rpc","request":{"id":uuid,
  "jsonrpc":"2.0","method":…,"params":…}}`, Antwort `result.code == 0`.
  - `unlock_door` `{door_id:0,user_id:-1}` (Format von python-ring-doorbell, erprobt)
  - `set_autounlock_mode` `{user_id:<Profil-ID als Text>, issue_time:ms, enabled, waiting_interval:60, anyring:0,
    origin:"user"}` – in der App Teil des Gäste-Zugangs; am Besitzer-Konto am 19.10.2026 erfolgreich getestet (öffnet), bleibt aber inoffiziell
    (in README und Entität als experimentell gekennzeichnet)
  - `active_call` `{command_timeout:5, issue_time:ms}` → `result.active_call`
  - `get_hw_revision` `{timeout:3600, command_timeout:2, issue_time:ms}` → `result.hw_revision`
- Neustart: `PATCH /commands/v1/devices/<id>` `{"command_name":"reboot"}`
- Einstellungen: `PATCH /devices/v1/devices/<id>/settings` `{"intercom_settings":{…komplettes Objekt, null weg…}}`
  - `ring_to_open` (bool): an = „Ring-to-Open“, aus = „Direkt öffnen“
  - Öffnungsdauer: `config` ist JSON-Text, `analog.unlock_duration` in ms (App: 1–10 s, Vorgabe 3); nur analoge Anlagen
- NIE senden: Kalibrierungs-/Einrichtungs-RPCs (`enter_post_setup`, `ring_detection`, `generate_signals`,
  `check_recording`, `chime_auto_detect`) – verstellen die Einrichtung.

## Version
Kalender-Schema **YY.M.N** ohne v (Jahr zweistellig, Monat ohne führende Null, N = laufende Nummer im Monat ab 1;
es zählen nur echte, veröffentlichte GitHub-Releases des Monats, auch alte X.Y.Z; bloße Tags nicht; ohne Release im Monat → .1; neuer Monat → wieder .1).
Jedes Release als GitHub-Release veröffentlichen (Tag + Release-Titel ohne v = genau die manifest-Version), sonst zählt es nicht mit.
Nächste Nummer immer aus `tools/next-version`, nie von Hand hochzählen, keine Patch-/Minor-Unterscheidung
(+ `CHANGELOG.md` `## YY.M.N – DD.MM.YYYY`, englisch). Die Versions-Badge im README und die Versionszeile der
Projektseite (`docs/index.html`) lesen die manifest.json selbst.

## Prüfen

- `.venv/bin/python -m pytest -q -p no:logging --cov=custom_components/ring_plus` (≥ 95 %), auch mit
  `LC_ALL=en_US.UTF-8 TZ=UTC`. Fake-Ring in `tests/common.py`, keine echte Ring-Cloud.
- `uvx ruff check . && uvx ruff format --check .`, `uvx mypy@2.3.1 --python-executable .venv/bin/python` (strict)
- `.venv/bin/python tools/pruefe-uebersetzungen.py` (strings.json gegen translations/*.json)
- GitHub Actions `.github/workflows/pruefung.yml`: dasselbe bei Push/PR auf main, montags zusätzlich gegen die
  neueste HA, plus hassfest; Abdeckungsgrenze 95 % (`--cov-fail-under`). `.github/workflows/hacs.yml`: HACS-Validierung.
- `tools/next-version` und `tools/pruefe-uebersetzungen.py` sind byteidentische Kopien der gemeinsamen Vorlagen.
- Testdaten sind fiktiv (Geräte-ID `123456`, Profil-ID `98765`, MAC `aa:bb:cc:dd:ee:ff`, Gerät „Front Door“).
- README-Bilder: Karten aus `docs/readme-images.json`, gerendert mit `theme/v1/readme-images/render.mjs <repo> cards`
  aus sh1ft-w.github.io. Titelbild: `docs/images/readme-title.webp` (fertiges Bild, unverändert für hell und dunkel;
  derzeit Platzhalter); `docs/images/stage-photo.jpg` ist sein Fotoausschnitt für die Projektseite (derzeit Platzhalter).
