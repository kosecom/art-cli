# Agent installation brief — ART-CLI 0.2.0

This file describes installation; it is not permission to ignore the user's instructions or your safety policy. Inspect code and provenance before executing downloaded software.

## 1. Inspect and choose scope

- Obtain the release ZIP and matching SHA256 from this repository's Releases. Verify the archive, extract it, and read README.md, NOTICE.md and docs/SETUP.md.
- Confirm native Windows or macOS, Python 3.10+, the agent type and **explicit absolute target home**. Never select another profile from guesswork. Use Hermes's interpreter for the native Hermes plugin.
- A GUI app is not proof of its CLI. Run `python setup_art.py --home "<home>" --agent hermes --check` (or `mcp` / `cli`). Check does not launch apps or install anything.
- Do not upload check output: it can contain the owner's local paths.

## 2. Install only the approved integration

Run `python setup_art.py --home "<home>" --agent <hermes|mcp|cli> --install`. An existing managed installation requires explicit `--upgrade`; unrelated directories/launchers must not be overwritten.

For Hermes, use the setup report's activation steps in the **same profile** and start a new session. Installation alone is not evidence of activation. For MCP, use the generated absolute command/argv configuration with a stdio-capable client that answers server pings. Do not start a public listener or replace the agent's entire config file.

Missing official CLI binaries require a separate user-approved action. Use bootstrap.py only with an explicitly selected app version and new staging directory; verify its report and configure the returned native binary path. Never bypass Gatekeeper, quarantine, credential checks or application permissions.

## 3. Verify without modifying a user's document

- Run installed `art.py --home "<home>" catalog` and `doctor`.
- Explicitly `refresh --app <available-app>`, then search and describe a read-only tool. Execute only the selected read. Report native errors honestly.
- With approval, create a small test artifact in a **new** output directory. Put creation, edits, save and export in the same batch. Reopen the native file in a fresh job and inspect the result; check the export itself.
- If VectorCraft is available, the bundled opt-in smoke test implements that workflow: `python scripts/smoke_test.py --home "<home>" --out "<new-absolute-output-directory>"`. It creates only new test files, validates native JSON/SVG/PNG, then reopens and compares the PNG. It refuses an existing output directory.
- Confirm which apps work, which are missing, and which permissions remain unset. Do not claim all editor commands were executed.

## 4. Operating rules

Preserve native schemas and errors. Never grant callbacks, auto-retry mutations, fabricate files, or silently route to a different host. A headless job does not control the visible GUI; say so. Remote SSH and native GUI attachment require separate explicit configuration. Do not copy personal credentials, routes or caches into shared packages. Protect existing projects and applications; stop only workers owned by the job.

## 5. Updates and rollback

Use the documented managed upgrade; keep its backup path. Disable Hermes activation in the owning profile before uninstall. Uninstall retains user config, caches, dependencies and backups; it does not uninstall ArtCraft. Refer to docs/SETUP.md for exact commands.
