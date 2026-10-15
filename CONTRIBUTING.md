# Contributing

Keep the public integration portable and independent of any developer's workstation.

1. Open an issue describing the intended change and its scope.
2. Add a failing regression test before fixing a defect.
3. Run `python -m unittest discover -s tests -v` in a compatible Hermes Python environment. Native plugin-adapter tests require the actual Hermes runtime; ordinary CI must report those as skips, not fake passes.
4. For generic Python CI, use `python scripts/run_portable_tests.py`; for full runtime tests use the command above. Synthetic tests never replace native-app acceptance.
5. Test Windows Job Object behavior on Windows and process-group behavior on macOS. Avoid OS-global changes and shared-service restarts.
6. Never include personal paths, tokens, app binaries, caches, customer files or unredacted logs. Keep install/upgrade/uninstall tests in temporary homes.
7. State what was actually exercised. Schema enumeration does not prove every feature or format.

Version metadata must agree across plugin, CLI, protocol client/server, installer and package. Build with `python scripts/build_package.py --label release`. Existing release artifacts are immutable; do not overwrite a published tag or ZIP.

Submit a focused pull request with tests, compatibility notes and any remaining limitations. Visual assets should retain editable source and honest generation provenance.
