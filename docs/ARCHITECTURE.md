# Architecture and extension contract

## Layers

1. `plugin.yaml` + root `__init__.py`: genuine native Hermes plugin, eight compact registration schemas, late profile-aware backend import. Registration does not open applications or network connections.
2. `art_cli/__main__.py`, `art.py`: the single public `art` CLI. `install.py` performs a drop-in installation and provides a profile-bound launcher without changing a global PATH.
3. `art_cli/api.py`: common dispatch for the plugin, CLI and optional MCP/SSH worker. No duplicated per-app mini CLI engines.
4. `config.py`: actual native host selection, explicit operator overrides, separate cache per app/mode, atomic metadata writes. No hardcoded personal hostnames or private paths in the reusable core.
5. `commands.py`: second disclosure layer for native editor registries. Original command fields/duplicate variants are retained. `search` is paginated; `describe` supplies parameters and invocation mapping.
6. `rpc.py`: stdio JSON-RPC, bounded frames and paginated tool discovery, exact native result/image/error blocks, unsupported approval callbacks refused.
7. `native.py`: full vendor CLI argv and optional stdin, bounded stdout/stderr, explicit timeouts, no shell interpretation or automatic mutation retry.
8. `control.py` + `control_profiles.json`: all audited native GUI-control wire variants, operator-only loopback bindings and private authentication files. Generic native method forwarding is not restricted to a small static subset. Live UI/command discovery remains the app's authority.
9. `processes.py`: explicit owned worker lifetimes. Windows uses a kill-on-close Job Object; macOS uses a new private process group. Cleanup is not a broad app-name/PID scan and must never kill a pre-existing user GUI.
10. `worker.py`: optional stdio MCP (one `art` tool) and trusted remote `art/dispatch` worker. Reads upstream while jobs run, has cancellation/EOF cleanup and reverse heartbeat. All underlying application workers are lazy.

## Lifecycle and state

- Cached catalog listing is process-free. Explicit discovery starts only the requested native app; explicit `refresh` lists every known app and reports missing dependencies rather than silently dropping rows.
- Batches preflight app/tool names and available current structural schemas before any tool call. State stays within a job. Dynamic `$art_ref` values only refer to prior results and are checked again against the actual argument schema.
- Native software performs authoritative detailed validation. ART-CLI's structural validator is intentionally **not** a claim of implementing the entire JSON Schema standard.
- Every job includes explicit persistence. A successful JSON-RPC exchange or CLI exit code is not proof of a saved/exported artifact. Reopen/readback remains part of the caller's workflow.
- A failed mutation is never automatically repeated. Completed earlier steps remain visible; completion uncertainty is explicit.
- GUI attachment is different: the user's independently running application owns that GUI state. A one-shot proxy can disconnect without closing that pre-existing GUI.

## Updating upstream applications

The binary identity includes the actual native path, size, modification timestamp and command-mode arguments; refresh also records SHA256. A changed identity invalidates cached metadata. Execution always obtains the actual running worker's tool schemas. Optional expected schema hashes allow a caller to refuse a changed surface.

There is no frozen global catalog whose mismatch permanently blocks updated apps. There is also no promise that a future upstream wire-protocol change is compatible: unknown protocols/auth models must be audited, not guessed or bypassed.

`bootstrap.py` stages an exact official release in a new directory only. It checks published archive checksums and available asset digests, safe archive members, expected executable identity and macOS code-sign integrity. It does not modify existing app installations, runtime routes or OS security settings.

## Security and scope

Operator config selects binaries/modes, optional trusted remote transports and private control endpoints. Model parameters cannot replace the GUI endpoint, token/key file, executable or shell command. TCP control accepts literal loopback addresses only. Remote work runs the whole operation on its native host via a separately configured trusted route; a platform mismatch is rejected.

ArtCraft GUI controls are **not** a universal file sandbox. Native restrictions, explicit file roots, OS permissions and actual user authorization remain relevant. Some upstream local controls are unauthenticated; loopback binding does not justify calling the entire system fully secure. Credentials are never included in capability caches or package manifests.

Source-audited method examples are hints, not allowlists. Raw CLI functions, native resources/prompts and GUI-control functions remain distinct so that an incomplete headless command mapping does not silently hide another native API.
