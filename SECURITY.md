# Security policy

ART-CLI is a local automation bridge, not a sandbox for untrusted native apps or malicious operator configuration. Supported security fixes target the latest release.

## Reporting

Use GitHub's **Report a vulnerability** / private advisory mechanism in this repository when available. Do not post credentials, private files, exploit payloads containing real secrets or full personal configurations in public Issues. If private reporting is unavailable, open a minimal non-sensitive issue requesting a private channel; withhold exploit details until one is agreed. No response-time SLA is promised.

## Trust boundaries

- Run native applications and binaries from trusted official sources.
- Only the operator config selects executable paths, GUI endpoints, credential files and remote routes. Keep that directory private.
- Native tools may read, write, render, export or delete files. Request minimum working roots; a model prompt is not OS access control.
- GUI loopback binding alone is not authentication. Some upstream control protocols have no authentication.
- Do not expose the stdio worker through an unauthenticated network server. SSH routes must already be trusted.
- Interrupted edits may be partial. No automatic replay or transactional rollback is promised.
- Use a current Python and agent runtime. Check release hashes, but understand that a hash published beside a ZIP is integrity evidence, not a cryptographic publisher signature.

The distribution excludes vendor binaries, credentials and personal runtime configuration. Test fixtures use synthetic peers. Fixed malformed worker-ID regressions are documented in CHANGELOG.md.
