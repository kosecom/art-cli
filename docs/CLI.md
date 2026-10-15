# ART-CLI für Hermes

**Ein natives Hermes-Plugin, eine CLI, Windows und macOS.** Acht kleine Einstiegstools erschließen die jeweils installierten ArtCraft-Anwendungen dynamisch. Keine dreizehn permanenten MCP-App-Server, keine Änderungen an Hermes-Core.

> Technische Referenz. Für den Einstieg siehe [Setup](SETUP.md) und [START-HERE](../START-HERE.md). Die bloße Zahl gelisteter Tools ist keine Garantie für jede GUI-Funktion.

## Installation aus diesem Paket

Voraussetzungen: Python 3.10+, eine funktionierende Hermes-Installation, die offiziellen ArtCraft-Anwendungen und passende **native CLI-Binaries**. Windows-App-Installationen enthalten diese normalerweise; auf macOS werden die separaten offiziellen Universal-CLI-Archive benötigt. GUI-Installation und CLI-Installation sind nicht dasselbe.

Neue native CLI-Abhängigkeiten lassen sich reproduzierbar separat bereitstellen:

```text
python bootstrap.py --app figcraft --version 0.6.0 --target "<NEUER-Abhaengigkeitsordner>"
```

Der Helfer wählt das native offizielle Release-Archiv, prüft veröffentlichte SHA256-Werte und vorhandene GitHub-Asset-Digests sowie auf Mac die Codesign-Integrität. Er verändert weder Apps noch Runtime-Auswahl oder Schutzmechanismen. Den im Manifest zurückgegebenen Binary-Pfad anschließend ausdrücklich in `config.json` wählen. Version und Architektur müssen zum Ziel passen; kein automatisches Update fremder Installationen.

1. ZIP entpacken. In der Paketwurzel steht `plugin.yaml` neben `__init__.py`, `art.py`, `install.py` und `art_cli/`.
2. Das gewünschte **Hermes-Profil-Home** ausdrücklich auswählen. Andere Profile werden nicht verändert.
3. Mit dem Python der gewählten Hermes-Runtime ausführen:

```text
python install.py install --home "<Hermes-Profil-Home>"
python install.py status --home "<Hermes-Profil-Home>"
hermes plugins doctor "<Hermes-Profil-Home>/plugins/art-cli" --ci
hermes plugins enable art-cli
hermes plugins show art-cli
```

Bei den Hermes-Befehlen muss dasselbe Profil aktiv sein (`HERMES_HOME` beziehungsweise der vorhandene Profil-Launcher). Windows: `python`, nicht ein möglicherweise fehlendes `python3`. macOS: der tatsächlich installierte Runtime-Python, nicht blind ein alter Checkout-venv.

Der Installer erzeugt `<Home>/bin/art.cmd` unter Windows beziehungsweise `<Home>/bin/art` unter macOS. Er ändert **keinen globalen PATH** und startet keine Gateways neu. Den vollständigen Launcher-Pfad verwenden oder das Verzeichnis selbst in den PATH aufnehmen. Alternativ funktioniert `python art.py` direkt aus dem entpackten Paket.

Tools werden in einer **neuen Hermes-Sitzung** geladen. Das Kopieren/Enable allein beweist nicht, dass ein bereits laufender Chat seine Tool-Liste gewechselt hat. Keine Bestätigungen für Reloads automatisch erzeugen.

Das öffentliche Repository ist https://github.com/kosecom/art-cli. Die empfohlene Ersteinrichtung erfolgt aus einem versionierten Release-ZIP über setup_art.py. Kein erfundenes `hermes plugins install --path` verwenden.

## Bedienung

Globale Optionen stehen vor dem Unterbefehl:

```text
art guide
art catalog
art refresh --app photocraft
art search blur --app photocraft
art describe photocraft command_run
art call photocraft command_list --args "{}"
art batch --file job.json
art native figcraft -- commands --json
art rpc photocraft resources/list --params "{}"
art --platform mac catalog
```

`--home` ist das Profil-Home; Konfiguration und Caches liegen in `<Home>/art-cli/`. `--platform mac` von Windows aus funktioniert nur mit einer **explizit konfigurierten, bereits vertrauenswürdigen** Remote-Route. Ohne Route wird nicht auf den falschen Host ausgewichen.

### Die acht Hermes-Einstiege

- `art_catalog`: Apps/Cache; optional `operation: doctor|refresh`.
- `art_search`: passende native Tools **und** Editor-Commands; `scope: tools|commands|all`.
- `art_describe`: exaktes natives Toolschema oder `kind: command` mit Parameterdokumentation und Aufrufweg.
- `art_execute`: einen nativen Tool-/Command-Aufruf.
- `art_batch`: zustandsbehaftete geordnete Schritte über eine oder mehrere Apps.
- `art_native`: gesamte originale CLI-Oberfläche als Argumentliste, ohne Shell-Interpolation.
- `art_rpc`: native Ressourcen/Prompts/Completion; konfigurierte GUI-Control-Verbindung über den dokumentierten Control-Pfad.
- `art_guide`: eingebauter Leitfaden, mit `app` zusätzlich die echte aktuelle Hersteller-CLI-Hilfe.

Jedes Tool nimmt das kompakte Feld `arguments`. Beispiel:

```json
{"arguments":{"app":"figcraft","query":"frame","scope":"commands"}}
```

### Zustand und Dateiablage

Ein einzelner Aufruf ist ein Job. Native Dokumente existieren **nicht automatisch im nächsten Aufruf weiter**. Erzeugen, Bearbeiten und Speichern/Exportieren gehören deshalb in **denselben Batch**. Bestehende Dateien nach einem fehlgeschlagenen Job erst prüfen; keine automatische Wiederholung mutierender Schritte. Fehler führen nicht zu einem Rollback.

```json
[
  {"app":"figcraft","tool":"create_node","arguments":{"type":"rectangle","name":"ART-CLI shape","width":160,"height":90}},
  {"app":"figcraft","tool":"set_properties","arguments":{"ids":[{"$art_ref":"0:/id"}],"props":{"fill":"#3366ff"}}},
  {"app":"figcraft","tool":"save_file","arguments":{"path":"/ABSOLUTE/OUTPUT/example.figcraft"}}
]
```

Das Beispiel ist eine Strukturhilfe: konkrete Pfade, gültige Dateierweiterung und aktuelle Parameter **vorher mit describe prüfen**. Plattformpfade bleiben native Pfade. Einen erfolgreichen Aufruf stets am gespeicherten Dokument/Export zurücklesen.

Dynamische Handles: `{"$art_ref":"0:/doc"}` ersetzt einen Wert durch `/doc` aus dem strukturierten Ergebnis des vorherigen Schritts 0. Bei reinem Text-MCP wird ein einzelner JSON-Textblock dekodiert. Vorwärtsverweise sind verboten; fehlende Handles stoppen den Job.

## Konfiguration

`<Home>/art-cli/config.json` ist betreiberseitige Konfiguration, kein Modell-Tool zum Start beliebiger Programme:

```json
{
  "version": 1,
  "apps": {
    "figcraft": {
      "executable": "/absolute/vendor/path/figcraft-cli",
      "modes": {"gui": {"args": ["mcp", "--attach", "OPERATOR_PORT"]}}
    }
  },
  "remotes": {}
}
```

PhotoCraft benötigt für Dateizugriffe ausdrücklich freigegebene Arbeitsordner. Im Betreiber-Config unter `apps.photocraft` setzen:

```json
{"automation":{"read_root":"/absolute/existing/workspace","write_root":"/absolute/existing/workspace"}}
```

Beide Verzeichnisse müssen existieren; unter Windows native absolute Pfade wie `D:/ArtProjects` verwenden. Ohne diese Rechte wird ein Save/Open nicht still freigeschaltet. Grenzen einer laufenden GUI werden nicht durch Headless-Einstellungen ersetzt.

Windows-Binary heißt `figcraft-cli.exe`. Die Mac-Beispielpfade sind Platzhalter, keine installierten Pfade. Eigene Konfiguration wird **nicht im verteilbaren Paket gespeichert**. Native GUI-Modi unterscheiden sich pro App; siehe [control.md](control.md). Nicht willkürlich `--connect` überall verwenden. GUI-Tokens ausschließlich aus geschützten Dateien, nie aus Chat, Command-Logs oder Paketdaten.

## Architektur / Disclosure

```text
Hermes (8 Tools) oder art CLI oder optionaler MCP (1 art-Tool)
               -> gemeinsame Python-Engine
               -> lokaler Metadaten-/Command-Cache
               -> nur bei Arbeit: native CLI/MCP/GUI-Control
               -> originaler nativer Ergebnisblock
               -> Ende: eigene Worker schließen
```

`catalog` startet keine App. App-bezogene kalte Discovery darf genau die gewählte App abfragen und beendet sie wieder. `refresh` ist explizite vollständige Metadatenabfrage. Suchergebnisse sind paginiert und melden nicht geladene Apps. Neue Binary-Versionen invalidieren den Cache; Ausführung validiert aktuelle native Schemas statt am alten eingefrorenen Katalog dauerhaft zu scheitern. Optionaler `schema_hash` verhindert Ausführung nach einer Schemaänderung.

Der lokale optionale MCP-Adapter startet mit `art mcp`; für vertrauenswürdige SSH-Routen `art worker`. Beide nutzen dieselbe Engine. Keine App-Worker im Leerlauf. Nicht unterstützte Reverse-Callbacks werden **abgelehnt**, niemals als Zustimmung ausgegeben.

## Wichtige Funktionsunterschiede

- Headless bearbeitet eigene Dokumentzustände; es steuert nicht still das sichtbare Fenster.
- GUI-Funktionen benötigen die native Control-/Attach-Verbindung. Druckdialoge, Audiohardware, Plattformdienste und interaktive Konten sind eigene Abnahmefälle.
- PdfCraft hat mehr Command-IDs als Headless-Mappings. Direkte Full-Tools und GUI-Control bleiben erreichbar; ein fehlendes Mapping wird nicht als funktionierende Funktion verkauft.
- FigCrafts MCP-Commandliste ist Text; für strukturierte Discovery nutzt ART-CLI das originale `commands --json`.
- DeckCraft liefert teilweise mehrere Varianten derselben Command-ID. Diese werden erhalten, nicht still gelöscht; Einträge und eindeutige IDs werden getrennt gezählt.

## Updates und Rückweg

```text
python install.py install --home "<Home>" --upgrade
python install.py status --home "<Home>"
hermes plugins disable art-cli
python install.py uninstall --home "<Home>"
```

Upgrade/Uninstall sichern den vorherigen Pluginordner unter `<Home>/art-cli/backups/`. App-Installationen, Benutzerdateien, Konfiguration, Dependency-Binaries und Caches bleiben erhalten. Ein vorhandener fremder Pluginordner oder `art`-Launcher wird nicht überschrieben. Wiederherstellung: bei deaktiviertem Plugin den gewünschten gesicherten Pluginordner nach `<Home>/plugins/art-cli` kopieren, `status`/`doctor` ausführen und erneut aktivieren. Keine pauschalen Prozess-Kills.

## Tests / Weiterentwicklung

```text
python -m unittest discover -s tests -p "test_*.py" -v
hermes plugins doctor . --ci
```

Pluginadapter-Tests benötigen die echte importierbare Hermes-Runtime; reine Transporttests verwenden ausdrücklich synthetische Peers. Native Windows-/Mac-Abnahme ist separat. Originale ArtCraft-Binaries, Forschungsmaterial, private Maschinenpfade und Kundendokumente gehören nicht ins Release-ZIP.
