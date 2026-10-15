# GUI control: exact public vendor methods, not a headless substitute

`art_cli.control.call_control(store, arguments, timeout=60)` is the reusable dispatch
boundary. The parent API routes a foreign `platform` to its trusted native host
**before** calling this function. This module refuses foreign platforms, never
falls back locally, and never sends credentials to a remote endpoint.

```json
{"app":"cadcraft","method":"control.methods","params":{}}
```

Allowed call fields: `app`, `method`, `params`, optional `control_name` and
`platform`. `params` is JSON data, not executable argv. Method names are passed
unchanged; they are **not** restricted to the headless tool list, static command
catalog, or the source hints. `auth` belongs to the transport, not to the caller.
The return envelope contains `ok`, `app`, `transport`, and `response`:

* TCP: `response` is the complete vendor response including `id`, native errors,
  and extension fields. No conversion of UI calls to engine commands.
* CLI: `response` is exactly the parsed native stdout JSON value (array/scalar/
  object supported). Nonzero exit codes are errors, never synthesized success.
* Photo MCP: `response` is the native `control_call` tool result, including content
  and `isError`. It is not silently unwrapped or rebuilt.

No native stderr, authentication reply, or credential is returned. A response
containing the credential is **withheld**, rather than silently rewritten. A
transport failure means the operation **may have completed**. No reconnect-and-
replay, retry, automatic installation, GUI start, open-port scan, or HTTP occurs.

## Operator binding (examples are templates, not live configuration)

The operator edits `<Hermes profile>/art-cli/config.json` on the native target
host. This implementation does not write it. Under `apps.<app>.control` set:

```text
CAD/Vector/Light/Fig/Film/Effect/Grid/Sound:
  endpoint: {host: "127.0.0.1", port: <operator-selected integer>}
Design/Deck:
  endpoint: {host: "127.0.0.1", port: <operator-selected integer>}
Photo:
  endpoint: {host: "127.0.0.1", port: <operator-selected integer>}
  token_file: <absolute private token file>
Word:
  endpoint: {host: "127.0.0.1", port: <operator-selected integer>}
  key_file: <absolute current window key file>
PDF:
  control_file: <absolute private app-written JSON file containing port and token>
```

There is no default port. Literal loopback IPv4 or IPv6 only; DNS names (including
`localhost`), URLs, non-loopback addresses, scoped addresses, and invalid ports
are refused before connecting. PDF's source-defined host is always loopback;
its port comes only from its private control file. The operator must confirm that
the selected port belongs to the intended application. Unauthenticated protocols
cannot cryptographically prove the peer's app identity.

Optional `transport: "tcp-jsonl"` explicitly selects the audited raw TCP path,
including for native-CLI apps. Otherwise each app uses the mode below. No caller
can override it. For multiple windows use
`control: {named: {windowA: <binding>, windowB: <binding>}}` and the call's
`control_name: "windowA"`; names select config, not commands or paths.

Credential/control files must be absolute regular files, not final symlinks;
reads are size-bounded with file identity checked after opening. Unix requires
current-user ownership and no group/other permissions (normally `0600`). On
Windows the **operator must provide a private directory and current-user-only
ACL**; portable stdlib checks do not constitute a Windows ACL audit. Do not put
these files or credentials in this package, artifacts, catalogs, or logs.

### Filesystem roots are not a universal sandbox

Network/executable/credential bindings cannot be overridden by call arguments.
PhotoCraft and VectorCraft support GUI automation roots: set them **when the
operator starts the app**, not per request. Their running-app authorization is
preserved; ART-CLI does not change roots or reroute a denied call through another
interface. Other vendors' headless `--automation-*-root` flags must **not** be
represented as confinement of an already-running GUI (Word and Sound explicitly
reject attach plus those headless roots). Generic GUI control can read/write
whatever the native process is authorized to access. This wrapper does not
pretend that checking strings in arbitrary vendor JSON can sandbox all methods.
Use a restricted OS account/container-equivalent host boundary when stronger
filesystem confinement is required; otherwise do not expose raw GUI control to
untrusted callers. Normal user approval rules still apply to edits, printing,
network operations and destructive UI actions.

## Source-grounded per-app modes

All commands below are **operator instructions only**. None were run during this
implementation. `PORT`, `TOKEN_FILE`, `CONTROL_FILE`, `READ_ROOT`, `WRITE_ROOT`
and executable locations are placeholders, not defaults. Use the actual native
Windows executable or macOS binary. On macOS a verified application bundle can
be opened by its operator with `open -a <actual app> --args ...`; ART-CLI itself
never invokes `open` or discovers bundles to launch them.

| App | Operator GUI start flags | Optional native MCP attach | ART-CLI default raw control |
|---|---|---|---|
| PhotoCraft | `photocraft --control PORT --control-token-file TOKEN_FILE --automation-read-root READ_ROOT --automation-write-root WRITE_ROOT` | `photocraft-cli mcp --bridge 127.0.0.1:PORT --control-token-file TOKEN_FILE` | Same native MCP bridge, `control_call {method,params}` |
| VectorCraft | `vectorcraft --control PORT --automation-read-root READ_ROOT --automation-write-root WRITE_ROOT` | `vectorcraft-cli mcp --connect 127.0.0.1:PORT` | TCP JSONL; explicit headless mode is `mcp --headless`, not implicit `mcp` |
| LightCraft | `lightcraft --control PORT` | `lightcraft-cli mcp --connect 127.0.0.1:PORT --compact` | TCP JSONL |
| PdfCraft | `pdfcraft --control CONTROL_FILE` | **No MCP GUI attach flag** | `pdfcraft-cli ui --control CONTROL_FILE ui.METHOD key=JSON ...` |
| CADCraft | `cadcraft --control PORT` | `cadcraft-cli mcp --connect 127.0.0.1:PORT` | TCP JSONL; never `--lazy`/`--launch` |
| FigCraft | `figcraft --control PORT` | `figcraft-cli mcp --attach PORT` | TCP JSONL; `--attach`, not `--connect` |
| DesignCraft | `designcraft --control PORT` | `designcraft-cli mcp --connect 127.0.0.1:PORT` | `designcraft-cli app --port 127.0.0.1:PORT --method METHOD JSON` |
| FilmCraft | `filmcraft --control PORT` | `filmcraft-cli mcp --bridge 127.0.0.1:PORT` | TCP JSONL |
| EffectCraft | `effectcraft --control PORT` | `effectcraft-cli mcp --bridge 127.0.0.1:PORT` | TCP JSONL |
| WordCraft | `wordcraft --control PORT` | `wordcraft-cli mcp --connect 127.0.0.1:PORT` (native key lookup) | TCP JSONL with **top-level `key` on every request**, read from configured `key_file` |
| DeckCraft | `deckcraft --control PORT` | `deckcraft-cli mcp --connect 127.0.0.1:PORT` | `deckcraft-cli app --port 127.0.0.1:PORT --method METHOD JSON` |
| GridCraft | `gridcraft --control PORT` | `gridcraft-cli mcp --connect 127.0.0.1:PORT` | TCP JSONL |
| SoundCraft | `soundcraft --control PORT` | `soundcraft-cli mcp --connect 127.0.0.1:PORT` | TCP JSONL; native `app METHOD JSON` remaps unknown methods to engine commands, so it is not the generic exact-method path |

Photo's raw protocol authenticates once per connection using
`{id:1,method:"auth",params:{token:...}}`, then sends
`{id:2,method,params}`. PDF authenticates similarly but uses **JSON-RPC 2.0**
requests/replies, not the other apps' `{ok,result/error}` envelope. Word's
`params.key` remains ordinary data (`ui.key {key:"Enter"}`); the credential is
separate at the request top level. All other audited TCP paths use
`{id,method,params}` / `{id,ok,result/error}` without invented auth headers.

PDF's CLI prepends `ui.` to names without that prefix and accepts only object
`key=value` parameters. Therefore arbitrary methods, non-object params, or keys
its CLI cannot faithfully represent use the audited PDF TCP JSON-RPC transport,
not a renamed method. Normal `ui.*` object calls retain the native CLI's private-
file checks. `--out` is never injected: screenshot payloads stay unchanged.

The Photo bridge supplies a full public raw method path. Design and Deck have
explicit `--method` dispatch. Other attached MCP servers expose a subset of GUI
controls, so TCP is necessary rather than silently hiding UI-only methods.

## Discovery and screenshots (read before acting)

| App | Source-confirmed discovery/state calls |
|---|---|
| Photo, Vector, Light, Design, Film, Effect, Sound | `engine.commands`, `ui.menu.list`, `ui.inspect` |
| CAD | `control.methods`, `engine.commands`, `ui.menu.list`, `ui.inspect` |
| PDF | `ui.commands`, `ui.state`, `ui.inspect` |
| Fig, Word, Deck, Grid | `engine.commands`, `ui.inspect` |

Every app's audited handler exposes `ui.screenshot`. Request its native params
without assuming common PNG field names, path requirements or display behavior.
For example Photo can return inline PNG without a path; Vector supports
`data:true` and `pngBase64`; Fig's documented screenshot needs a path; Light can
fall back to CPU/headless rendering. A returned image is **not** proof that a
visible native frame was presented. CAD's `control.methods` is a real method;
it is not invented for vendors lacking it. Do not call an unsupported common
"methods" API and claim complete discovery.

Raw methods retain UI-specific behavior: menu invocation may open dialogs while
`engine.execute` may run commands directly. Query state/enablement before and
after an action. Printing in Word has GUI-only commands; PDF headless command
mapping is partial. Fig headless window commands can be no-ops. Generic method
access avoids those catalog restrictions but does not prove every gesture works.

## Evidence and portability

`art_cli/control_profiles.json` records all 13 release commits, handler/document
paths, source-derived discovery methods and non-exhaustive method hints. Hints
are **never** an allowlist or a substitute for the live app. Primary evidence:

* Visual apps: `research/group-visual/<app>.json`, `FINDINGS.md`, and the pinned
  `source/<app>/docs/control-protocol.md`, `crates/ui-egui/src/control.rs`.
* Vector/Light/CAD/Fig/Design transport envelopes:
  `source/<app>/crates/mcp/src/backend.rs`.
* Photo auth/roots and full raw bridge: its `docs/control-protocol.md`.
* PDF native private-file checks and argv handling:
  `source/pdfcraft/apps/pdfcraft-cli/src/main.rs:814-905`; TCP authentication:
  `source/pdfcraft/crates/ui-egui/src/control.rs:790-856`.
* Design native raw dispatch: `apps/designcraft-cli/src/main.rs:439-465`.
* Media apps: `research/group-media/<app>-report.json`, pinned
  `source/<app>/<app>-<commit>/apps/<app>/src/control_server.rs`,
  `crates/ui-egui/src/control.rs` and `docs/control-protocol.md`.
* Deck native raw dispatch: `apps/deckcraft-cli/src/main.rs:303-332`;
  Sound method rewriting: `apps/soundcraft-cli/src/main.rs` (`app_request`, `app`).

Stdlib-only Python >=3.10; subprocess argv arrays and native paths work on Windows
and macOS. Response reads are bounded (64 MiB), finite JSON is required, and TCP
uses one total deadline across auth and reply; CLI timeout kills only its owned
CLI child. Credentials are read only on the selected native host. These tests
were run on native Windows; macOS execution and real GUI acceptance remain open.

Run `python -m unittest discover -s tests -p test_control.py -v`.
Tests use explicitly synthetic ephemeral loopback peers and a Python stand-in
CLI. They verify all 13 wire profiles, credential separation/suppression,
no-connect-without-config, loopback enforcement, native bridge argv, exact
payloads/errors, invalid/oversized responses, timeouts and no replay. They do
**not** start any real GUI, modify live configuration, or claim all UI gestures
were exercised.
