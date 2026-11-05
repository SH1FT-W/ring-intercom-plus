# Ring Intercom Plus – Projektregeln

HA-Integration (`custom_components/ring_plus`, Domain `ring_plus`) mit Zusatzfunktionen für die **Ring Intercom**
(Türöffner, Klingel, Anruf aktiv, Nächstes Klingeln öffnet, Öffnungsdauer, Ring-to-Open, Neustart, Diagnose).
Ergänzt die offizielle HA-Integration `ring` und nutzt deren Anmeldung; kann die Intercom-Funktionen von ring-mqtt
ersetzen. An echter Hardware geprüft: Ring Intercom (Audio).

- Repo wird **öffentlich**: nichts Persönliches ins Repo (keine Namen, echten Entity-IDs, Geräte-/Profil-IDs,
  Seriennummern, Heimnetz-Details, lokalen Pfade). Testdaten bleiben fiktiv (Geräte-ID `123456`, Profil-ID `98765`,
  MAC `aa:bb:cc:dd:ee:ff`, Gerät „Front Door“).
- README, CHANGELOG, Release-Notizen, Issue-Texte und Commit-Texte auf Englisch.
- Lokal committen ok, Push und Releases nur nach Rückfrage.
- **Keine echten Geräte ansteuern:** Öffnen-Befehle öffnen eine echte Tür. Live-Tests nur mit dem Besitzer.

## Aufbau

- `__init__.py` Einstieg, holt die Ring-API aus dem geladenen `ring`-Eintrag, Klingel-/Entsperr-Handler.
- `coordinator.py` je Intercom (Einstellungen, „Nächstes Klingeln öffnet“, Zeitplan), `api.py` Ring-Befehle ohne HA,
  `storage.py` neustartfester Stand, `entity.py` gemeinsame Basis inkl. Fehler-Wrapper `_run` (nicht je Plattform kopieren).

## Warum es so ist (steht nicht im Code)

- Keine eigene Anmeldung, keine zweite Push-Verbindung: alles kommt aus dem `ring`-Eintrag (`runtime_data`) und
  dessen Event-Entitäten. Ändert HA diesen Aufbau, bleibt Ring Intercom Plus in „Wird erneut versucht“ mit Meldung im Log.
- Entitäten hängen per `entity.device_entry` am Gerät der Ring-Integration: seit HA 2026.9 gelten Gerätekennungen
  nur je Integration, `device_info` würde ein zweites Gerät anlegen.
- „Nächstes Klingeln öffnet“ ab 2 min und per Zeitplan öffnet HA selbst, nur bei neuem Ring-Push-Alarm (neue `id`,
  frisch): die Event-Entitäten feuern bei jedem Geräte-Ereignis erneut, solange ein Alarm lebt. Nie über den
  Ersatzweg „Letzte Aktivität“. 1 min = Intercom-eigener Modus (`set_autounlock_mode`).
- Ohne PIN öffnen auch Dashboards/Automationen ohne Code (bewusster Standard).
- Wer von ring-mqtt kommt, kann die neuen Entitäten auf die alten Entity-IDs umbenennen; Ring Intercom Plus setzt
  keine festen Entity-IDs voraus.

## Protokoll (aus der Ring-Android-App 3.111.1, Formate in `api.py`)

- `set_autounlock_mode` ist in der App Teil des Gäste-Zugangs; am Besitzer-Konto am 19.10.2026 erfolgreich getestet
  (öffnet), bleibt aber inoffiziell (in README und Entität als experimentell gekennzeichnet).
- `unlock_door` `{door_id:0,user_id:-1}` ist das Format von python-ring-doorbell (erprobt).
- Öffnungsdauer gibt es nur bei analogen Anlagen (App: 1–10 s, Vorgabe 3).
- NIE senden: Kalibrierungs-/Einrichtungs-RPCs (`enter_post_setup`, `ring_detection`, `generate_signals`,
  `check_recording`, `chime_auto_detect`) – verstellen die Einrichtung.

## Version
Versionen über `tools/next-version` (globale Regeln). CHANGELOG `## YY.M.N – DD.MM.YYYY`, englisch. Die
Versions-Badge im README und die Versionszeile der Projektseite (`docs/index.html`) lesen die manifest.json selbst.

## Prüfen

- `.venv/bin/python -m pytest -q -p no:logging --cov=custom_components/ring_plus` (≥ 95 %), auch mit
  `LC_ALL=en_US.UTF-8 TZ=UTC`. Fake-Ring in `tests/common.py`, keine echte Ring-Cloud.
  `tests/test_ha_ring.py` richtet die echte HA-Ring-Integration der installierten HA-Version ein (nur Netz/Push
  von ring_doorbell gefälscht) und prüft die Annahmen aus `docs/ha-annahmen.md`; ihre Pakete stehen in
  `requirements_test.txt` und müssen bei einem HA-Update zu den Manifesten von `ring`/`ffmpeg`/`camera` passen.
- `uvx ruff@0.16.9 check . && uvx ruff@0.16.9 format --check .` (Version wie in pruefung.yml),
  `uvx mypy@2.3.1 --python-executable .venv/bin/python` (strict)
- `.venv/bin/python tools/pruefe-uebersetzungen.py` (strings.json gegen translations/*.json)
- GitHub Actions `.github/workflows/pruefung.yml`: dasselbe bei Push/PR auf main, montags zusätzlich gegen die
  neueste HA, plus hassfest; Abdeckungsgrenze 95 %. `.github/workflows/hacs.yml`: HACS-Validierung.
- `tools/next-version` und `tools/pruefe-uebersetzungen.py` sind byteidentische Kopien der gemeinsamen Vorlagen.
- README-Bilder: Titelbild aus `docs/readme-images.json` mit `theme/v1/readme-images/render.mjs <repo>`
  aus sh1ft-w.github.io: Titel als `docs/images/readme-title-{light,dark}.webp` (2560 × 1280, Fenster zeigt
  `docs/images/title-shot-*.png`, den Funktionsblock der Projektseite mit 2× aufgenommen) plus `readme-title-social.png`
  für die GitHub-Vorschau; README-Aufbau nach `repo-vorlagen/readme-muster.md`, ohne Kartentabellen. Die Projektseite zeigt das Titelbild im Hero.
