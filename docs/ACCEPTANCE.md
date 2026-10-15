# Verification and limitations

## Native pre-public audit

The installed integration was exercised on native Windows and macOS, not only in mocked tests:

- Eight native Hermes tool entrypoints discovered from the installed plugin.
- 13 local read-only app workflows per host and 13 remote reads in each direction. All 26 remote native payloads exactly matched destination-local payloads.
- Each host: 728 native tool schemas retrieved and checked against their declared JSON Schema draft; 6,704 editor entries described, representing 6,702 distinct per-app command IDs. Duplicate native variants are retained.
- Twenty additional FigCraft lifecycle jobs per host; owned PID + creation time tracked, no surviving owned processes.
- Production 64 MiB input/output bounds, malformed JSON, duplicate/nonfinite input, MCP stdout/EOF, busy responses, cancellation and independent concurrent jobs checked.
- Both worker ID crashes found in that audit were fixed. The post-fix suite passed 89 tests on Windows and 83 on macOS, with six Windows-only skips. The public release adds onboarding/version tests; see CI and release notes for its exact counts.

These are historical counts for tested upstream versions, not hardcoded requirements for all future ArtCraft versions. This is **metadata coverage, not execution of every native tool/editor command**.

## Public release acceptance

The release process verifies a clean-profile install from the candidate ZIP on native Windows and macOS, explicit activation in an isolated Hermes home, native read/create/save/export/fresh-reopen behavior using available native CLIs, and managed upgrade/removal. No live customer profile is used as the clean-install fixture. Dependencies or missing standard-path discovery must be reported, never hidden by importing a private configuration.

The public release includes a redacted machine-readable verification summary under `docs/release-verification.json` when accepted. Raw developer paths, profiles and process logs are intentionally not published. CI tests protocol/installer contracts with synthetic peers; it does not install proprietary/native app binaries or claim native-app acceptance on hosted runners.

## Examples and proof boundaries

A geometric logo was created with the native Windows VectorCraft engine, saved in editable native format, exported to SVG/PNG, reopened in a fresh worker and re-exported with matching pixels. The repository graphics use that same engine-driven approach. They are not screenshots of a GUI editing session.

- Background-engine output does not imply GUI attachment or a recent-project entry.
- Some editor commands need a native GUI; not all registry IDs have headless mappings.
- Fonts, codecs, hardware, accounts, permissions and platform services remain separate dependencies.
- Native app updates may change schemas or protocols. Refresh invalidates stale metadata; unknown auth/protocols require investigation rather than guessed workarounds.
- MCP clients must support stdio and reply to server heartbeat pings. No assertion is made that every commercial agent client was tested.
- Explicit remote routing requires operator-managed SSH/access. It is not bundled or configured automatically.
- Application approval callbacks are not auto-granted. GUI loopback control is not a universal file sandbox.

Consult [architecture](ARCHITECTURE.md), [control details](control.md), [setup](SETUP.md) and the [security policy](../SECURITY.md).

