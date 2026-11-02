# HA-Annahmen

<!-- Vorlage aus repo-vorlagen/vorlagen/ha-annahmen.md. Der HA-Beta-Bericht (repo-vorlagen/ha-beta-bericht.md)
     gleicht diese Liste jeden Monat mit den Neuerungen der HA-Beta ab. Nur festhalten, was bei einer Änderung in HA
     still kaputtginge. -->

Worauf sich dieses Repo bei Home Assistant verlässt. Bei jeder Änderung am Code mitpflegen.

**Getestet mit:** HA 2026.9.3 (ring-doorbell 0.9.14) · **Mindestversion:** 2026.9.0 (`hacs.json`)

`tests/test_ha_ring.py` richtet die **echte** HA-Ring-Integration der installierten HA-Version ein (nur das Netz
unter `ring_doorbell.Auth` und der Push-Empfänger sind gefälscht) und lädt Ring Intercom Plus darauf. Die übrigen
Tests nutzen einen nachgebauten Ring-Eintrag (`tests/conftest.py`) und prüfen nur das eigene Verhalten.

## Annahmen

| Annahme | Wo im Code | Abgesichert durch |
|---|---|---|
| Der geladene `ring`-Eintrag hat `runtime_data.api` = `ring_doorbell.Ring` mit `async_query(url, method=…, json=…)`; alle eigenen Cloud-Aufrufe laufen darüber (keine eigene Anmeldung) | `__init__.py` `async_setup_entry.query` (Z. 59–65) | `test_ha_ring.py::test_runtime_data_shape`, `::test_ring_plus_runs_on_real_ring` |
| `runtime_data.devices.all_devices` liefert die Geräte mit `kind`, `id`/`device_api_id` (Cloud-ID), `device_id` (MAC), `name` | `__init__.py` Z. 68–72, 82–95 | `test_ha_ring.py::test_runtime_data_shape`; Fehlerpfad (Aufbau anders → ConfigEntryNotReady): `test_setup.py::test_ring_structure_changed` |
| `runtime_data` ist erst gesetzt, wenn der Eintrag `LOADED` ist | `__init__.py` `_ring_entry` | `test_setup.py::test_waits_for_ring`, `::test_ring_unloaded_at_runtime` |
| Ring-Gerät in der Device-Registry mit Kennung `("ring", <MAC>)`, je Integration (seit 2026.9 `async_get_device_by_identifier(…, config_entry_id)`) | `__init__.py` Z. 83–85 | `test_ha_ring.py::test_entity_unique_ids_and_device`, `test_setup.py::test_attached_to_ring_device` |
| Eigene Entitäten hängen über `Entity.device_entry` am fremden Ring-Gerät (kein zweites Gerät über `device_info`) | `entity.py` `RingPlusEntity.__init__` | `test_ha_ring.py::test_ring_plus_runs_on_real_ring`, `test_setup.py::test_attached_to_ring_device` |
| Ring-Event-Entitäten mit unique_id `<api_id>-ding` und `<api_id>-intercom_unlock`; ihr Zustand (Zeitstempel) ändert sich bei jedem Push | `__init__.py` `_listen_for_dings` (Z. 124–132) | `test_ha_ring.py::test_entity_unique_ids_and_device`, `::test_push_ding_and_unlock_reach_ring_plus` |
| Ring-Sensor `<api_id>-last_activity` (wird regelmäßig abgefragt) mit Attributen `category` (`ding`) und `created_at` | `__init__.py` Z. 134, `_activity_handler` | `test_ha_ring.py::test_last_activity_fallback_reaches_ring_plus` |
| Registry-Ereignis `EVENT_ENTITY_REGISTRY_UPDATED` mit `action`, `entity_id`, `old_entity_id` (Umbenennen/spätes Auftauchen) | `__init__.py` `_registry_updated` | `test_setup.py::test_ding_entity_renamed`, `::test_ding_entity_appears_later` |
| `SIGNAL_CONFIG_ENTRY_CHANGED` liefert `(ConfigEntryChange, ConfigEntry)`; Wechsel des `ring`-Eintrags nach `LOADED` oder `REMOVED` | `__init__.py` `_watch_ring_entry` | `test_setup.py::test_ring_reload_reloads_ring_plus`, `::test_ring_removed` (mit nachgebautem Ring-Eintrag) |
| `ConfigEntry.async_create_background_task` für die `active_call`-Abfrage, Abbruch beim Entladen | `coordinator.py` `_start_call_poll` | `test_control.py::test_unload_cancels_timers`, `::test_second_ding_replaces_running_call_poll` |

## Fremde Integrationen

- `ring` (HA-Kern): `runtime_data.api` / `.devices.all_devices` (Cloud-Zugang und Geräteliste), Gerät in der
  Device-Registry, `event.*` mit unique_id `<api_id>-ding` / `-intercom_unlock`, `sensor.*` `<api_id>-last_activity`
  mit Attributen `category`, `created_at` (alles `__init__.py`).
- Indirekt `ring_doorbell` (Bibliothek der Ring-Integration): `Ring.async_query`, Geräte-Attribute (`kind`, `id`,
  `device_id`, `name`) und `INTERCOM_KINDS` (Kopie in `const.py`).

## Nicht abgesichert

- Ob die Ring-Cloud die eigenen Endpunkte (`device_rpc`, `settings`, `/clients_api/profile`) weiter so beantwortet,
  prüft kein Test; das ist keine HA-Annahme (Fake in `tests/common.py`).
- Der echte Push-Empfänger (FCM) von ring_doorbell ist im Test ersetzt; geprüft wird nur, dass ein Push-Ereignis
  über die Event-Entitäten von HA Ring bei Ring Intercom Plus ankommt.

## Prüfbefehl

Gegen die gepinnte HA (`requirements_test.txt`; bei anderer HA-Version die Pakete aus den Manifesten von
`ring`, `ffmpeg` und `camera` mit anpassen):

```sh
uv venv --python 3.14 && uv pip install -r requirements_test.txt pytest-cov
LC_ALL=en_US.UTF-8 TZ=UTC .venv/bin/python -m pytest -q -p no:logging tests/test_ha_ring.py
```

Gegen die neueste HA: GitHub-Job „Tests gegen neueste HA (Frühwarnung)“ in `.github/workflows/pruefung.yml`
(montags, entfernt die Pins aus `requirements_test.txt`).
