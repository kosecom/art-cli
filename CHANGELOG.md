# Changelog

## 0.2.0 — First public package

- Agent-oriented onboarding entrypoint with explicit target home, read-only checks and Hermes / CLI / stdio-MCP connection guidance.
- English/German introduction, installation brief, security policy and shareable VectorCraft-created explanation graphics.
- Public source/release packaging without private profiles, host routes, vendor binaries or test documents.
- Consistent version metadata across installer, plugin and protocol clients/server.
- Includes both independently reproduced worker fixes: invalid cancellation IDs and invalid heartbeat-response IDs are rejected before dictionary access. Booleans and floats cannot alias integer job IDs.
- JSON CLI output is explicitly UTF-8, including redirected legacy-codepage Windows consoles; a forced-CP1252 regression test covers the hosted-CI finding.
- Regression tests preserve valid cancellation, heartbeat responses and continued worker usability.

The pre-public audit covered 13 app families on native Windows/macOS. Dynamic schemas depend on installed upstream releases. No compatibility promise for every agent UI, GUI operation or export combination is implied.
