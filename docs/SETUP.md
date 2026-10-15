# Portable ART-CLI setup

`setup_art.py` uses only Python's standard library (Python 3.10+). Run it from a trusted release extraction or repository checkout. Keep the complete package together: it imports `art_cli` and the sibling `install.py`; it is not a single-file downloader.

## Choose the exact target

`--home` is required and must be an absolute directory path. For Hermes, pass the **specific profile's home directory**, not its profile name or the directory containing all profiles. For MCP or standalone CLI use, choose a dedicated directory. There is no inferred current profile. Relative, empty, parent-traversal, and file targets are rejected. The existing installer also rejects symlinks/junctions in managed paths.

Example Windows target: `C:/ArtWorkspace/art-home`. For the default Hermes profile on macOS, a shell-expanded `"$HOME/.hermes"` is a possible target; named profiles have different homes. Replace examples with your intended location. Do not install into a directory shared by unrelated users.

```text
python setup_art.py --home "C:/ArtWorkspace/art-home" --check
python setup_art.py --home "C:/ArtWorkspace/art-home" --install --agent cli
python setup_art.py --home "C:/ArtWorkspace/art-home" --install --upgrade --agent cli
```

On macOS, use your Python 3.10+ executable (often `python3`) and an absolute macOS target path. **Actual installation is limited to native Windows and macOS.** Read-only checks are allowed on other platforms, but do not prove support for running the apps there.

## Check is the default

Omit `--install` and the helper only checks. `--check` is explicit documentation of that default; it cannot be combined with `--install`. Checks do not create the target directory, write configuration, run subprocesses/native apps, download, or start services. Import bytecode caching is disabled by the entry point.

The report uses `art_cli.config.Store(home).executable(app)` to inspect configured/default native CLI availability. This is **path discovery, not an app execution or license/health test**. One app may be available while others are missing. Missing apps are warnings, not failed installation. An absent ART-CLI installation is also a valid check result (`ok: true`, `installed: false`). Existing managed installation integrity is checked through the installer status API; tampering fails the check.

## Installation and upgrade

`--install` calls the existing `install.install(source, home, upgrade=...)` API, then reads back installer status. It installs into `HOME/plugins/art-cli` with the installer's local launcher. `--upgrade` requires `--install`; the installer retains the prior managed installation backup and reports its path in `installation.backup`. It refuses an unmanaged conflicting installation. Keep backup paths private if sharing reports.

All three agent choices use this same portable installation layout:

- `--agent cli` (default): use the returned `cli_command` argv and append an ART-CLI subcommand.
- `--agent mcp`: use the returned stdio configuration in your MCP client.
- `--agent hermes`: install the plugin files, then explicitly enable the plugin using Hermes.

The helper never changes global PATH, an MCP client's configuration, Hermes `config.yaml`, another profile, or a running service. Native app installation, authentication, licenses, and testing actual creative operations remain separate tasks.

## MCP: stdio only

```text
python setup_art.py --home "C:/ArtWorkspace/art-home" --install --agent mcp
```

After verified installation (and on subsequent checks), `mcp_config` contains a portable client configuration fragment of this shape:

```json
{
  "mcpServers": {
    "art-cli": {
      "command": "ABSOLUTE_PATH_TO_CURRENT_PYTHON",
      "args": ["ABSOLUTE_HOME/plugins/art-cli/art.py", "--home", "ABSOLUTE_HOME", "mcp"]
    }
  }
}
```

Use the **actual returned values**, not these placeholders. Arguments remain separate array items, including paths with spaces. The interpreter is the absolute current Python executable; moving/deleting that interpreter or moving the installation requires regenerating the configuration. Some clients use a different outer configuration schema; preserve `command` and `args` while adapting that wrapper. No daemon, HTTP endpoint, or public port is created, and setup does not start the MCP server.

## Hermes activation is deliberately manual

```text
python setup_art.py --home "C:/ArtWorkspace/art-home" --install --agent hermes
```

The JSON `activation` object includes the exact `command`, target `HERMES_HOME` environment override, and quoted PowerShell/POSIX commands. Run the appropriate command yourself in a fresh terminal **with Hermes installed and available**. For the example Windows target:

```powershell
$env:HERMES_HOME = 'C:/ArtWorkspace/art-home'; hermes plugins enable art-cli
```

For the example macOS target:

```sh
HERMES_HOME="$HOME/.hermes" hermes plugins enable art-cli
```

Review the Hermes consent prompts. Use a new Hermes session afterward; setup does not restart anything. The helper only checks whether a `hermes` command is on PATH; it does not import or execute that runtime or verify existing activation. `active: null` means unknown, and `performed: false` means this helper did not activate it. A previously active installation is not disabled.

`--install --agent hermes --activate` is accepted as an explicit activation request, but **does not automate activation**. It still installs and verifies files, then reports `installed: true`, `ok: false`, `activation.status: "manual_required"`, and exit code **3**. This prevents scripts from treating a deferred activation as success. `--activate` without both required options is rejected before mutation.

Why defer? The inspected Hermes native API is `load_config()` (merged, environment-expanded configuration) and `save_config(config, *, strip_defaults=True, preserve_keys=None, merge_existing=False)`. Neither takes an arbitrary target-home argument. Correct profile binding, configuration preservation, and plugin capability consent belong to the Hermes CLI; blindly serializing merged settings or bypassing plugin admission would be unsafe. This helper never calls those APIs or rewrites YAML, preserving unrelated configuration byte-for-byte.

References: [Hermes plugins](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins), plus the installed runtime's `hermes_cli/config.py`, `hermes_cli/plugins_cmd*.py`, and home-selection logic in `hermes_constants.py` were inspected for this implementation.

## Optional native CLI downloads require a separate explicit step

Setup performs no downloads. For each missing app you actually want, first choose and review a pinned official version. Then explicitly run the separate staging tool:

```text
python bootstrap.py --app APP --version PINNED_VERSION --target NEW_DIRECTORY
```

Replace the placeholders; inspect `python bootstrap.py --help` for supported app names. This is an **opt-in download to a new staging directory**, not installation or automatic route selection. Review the staged artifact and use the documented native-app installation/configuration flow. Never use an unreviewed moving version as a substitute for a pin.

## JSON and exit codes

Normal runs and errors print one JSON object to stdout. `--help` uses conventional text help. Reports contain local filesystem paths by design; review before posting publicly.

| Exit | Meaning |
| --- | --- |
| 0 | Check completed or installation verified; missing apps can still be warnings. |
| 1 | Installer, integrity, configuration-read, or filesystem failure. |
| 2 | Invalid arguments/path or unsupported installation platform; no install attempted. |
| 3 | Installation verified, but explicitly requested Hermes activation remains manual. |

`installed` is integrity-verified package presence, not native-app availability or Hermes activation. `mcp_config` is `null` unless a valid managed installation is present. On an exception, inspect `error`/`error_type`; do not infer installation or rollback state from missing fields. Installation rollback/backup semantics are those of `install.py`.

## Tests and recorded verification

```text
python -m unittest discover -s tests -p test_setup_art.py -v
python -m unittest discover -s tests -p "test_install*.py" -v
```

Windows-native Python 3.14 verification: **6 onboarding tests passed; 10 existing installer tests passed**. A separate subprocess smoke test of the full source package passed absent-target check, actual isolated install, integrity readback, and exact MCP argv validation. Python 3.10 grammar parsing passed for both new Python files (this is not a Python 3.10 runtime test). TDD red/green runs covered the initially missing helper, install/MCP delegation, then argument validation and deferred activation. The suite uses disposable targets and a minimal local fake package with the real installer to verify install, conflict, backed-up upgrade, integrity failure, and unchanged unrelated Hermes config. Additional coverage checks no subprocess during checks, partial app availability, exact home/MCP arguments, and unsupported-platform rejection. The public release candidate was subsequently verified on native Windows and macOS in fresh target profiles: 96 tests passed on Windows; 90 passed on macOS with six Windows-only skips. Both completed install, explicit isolated Hermes activation, all eight entrypoints, native VectorCraft save/export/fresh reopen, backed-up upgrade and uninstall. No live profile config was imported. Standard discovery found 13 CLIs on Windows and 12 on macOS (FigCraft needs a separately selected path there). See [release verification](release-verification.json).
