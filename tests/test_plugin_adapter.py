"""Run using the installed Hermes runtime: python -m unittest discover -s tests -p test_plugin_adapter.py -v."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class PluginAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox = tempfile.TemporaryDirectory(prefix="art-plugin-test-")
        cls.home = Path(cls.sandbox.name)
        cls.env = patch.dict(os.environ, {"HERMES_HOME": str(cls.home)})
        cls.env.start()
        # Real native classes, not local substitutes. Import only inside sandbox.
        from hermes_cli.plugins import PluginContext, PluginManager
        from hermes_cli.plugins_manifest import PluginManifest
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        cls.reset_home = staticmethod(reset_hermes_home_override)
        cls.token = set_hermes_home_override(str(cls.home))
        cls.manager = PluginManager()
        cls.manifest = PluginManifest(name="art-cli", path=str(ROOT), source="user")
        cls.ctx = PluginContext(cls.manifest, cls.manager)
        spec = importlib.util.spec_from_file_location("art_plugin_adapter_test", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
        cls.adapter = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.adapter
        spec.loader.exec_module(cls.adapter)
        cls.handles = []
        original = cls.ctx.register_tool
        def track(**kwargs):
            handle = original(**kwargs)
            cls.handles.append(handle)
            return handle
        cls.before_path = list(sys.path)
        cls.before_threads = {t.ident for t in threading.enumerate()}
        with patch.object(cls.ctx, "register_tool", side_effect=track), patch.object(cls.adapter, "_dispatch", side_effect=AssertionError("registration must be inert")):
            cls.adapter.register(cls.ctx)

    @classmethod
    def tearDownClass(cls):
        for handle in reversed(cls.handles):
            if handle is not None:
                handle.dispose()
        cls.reset_home(cls.token)
        cls.env.stop()
        for name in list(sys.modules):
            if name == "art_plugin_adapter_test" or name.startswith("art_plugin_adapter_test."):
                del sys.modules[name]
        cls.sandbox.cleanup()

    def entry(self, operation):
        from tools.registry import registry
        return registry.get_entry("art_" + operation, scope=self.manager.scope_key)

    def test_real_context_registration_is_inert_and_scoped(self):
        self.assertEqual(sys.path, self.before_path)
        self.assertEqual({t.ident for t in threading.enumerate()}, self.before_threads)
        self.assertEqual(len(self.handles), 8)
        self.assertTrue(all(self.handles))
        for op in self.adapter._DESCRIPTIONS:
            self.assertIsNotNone(self.entry(op))
        self.assertNotIn("art_plugin_adapter_test.art_cli.api", sys.modules)
        self.assertFalse(list(self.home.rglob("config.yaml")))

    def test_all_operations_preserve_results_and_arguments(self):
        native = {"ok": False, "platform": "windows", "steps": [{"app": "test-only", "tool": "test-only", "result": {"isError": True, "content": [{"type": "image", "data": "AA==", "mimeType": "image/png"}, {"type": "text", "text": "Grüße"}], "nested": [None, 0, False]}}], "error": {"code": "APP_ERROR"}}
        for operation in ("catalog", "search", "describe", "execute", "batch", "guide", "doctor", "refresh", "native", "rpc"):
            with self.subTest(operation=operation):
                args = {"callback": "await-user", "approved": False, "mode": "headless", "platform": "windows", "timeout": 30}
                envelope = {"arguments": args}
                tool = operation
                if operation in ("doctor", "refresh"):
                    tool = "catalog"
                    envelope["operation"] = operation
                with patch.object(self.adapter, "_dispatch", return_value=native) as dispatch:
                    result = self.entry(tool).handler(envelope, task_id="not-forwarded", approval_callback=lambda: self.fail("must not approve"))
                self.assertEqual(json.loads(result), native)
                dispatch.assert_called_once_with(operation, args, home=self.home)

    def test_profile_resolved_per_call(self):
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        other = self.home / "profiles" / "other"
        token = set_hermes_home_override(str(other))
        try:
            with patch.object(self.adapter, "_dispatch", return_value={}) as dispatch:
                self.entry("guide").handler({})
            dispatch.assert_called_once_with("guide", {}, home=other)
        finally:
            reset_hermes_home_override(token)

    def test_errors_are_json_and_do_not_reexecute(self):
        with patch.object(self.adapter, "_dispatch", side_effect=RuntimeError("native failure")) as dispatch:
            result = json.loads(self.entry("execute").handler({}))
        self.assertEqual(result["error"]["message"], "native failure")
        dispatch.assert_called_once()
        for bad in (None, {"arguments": []}, {"operation": "execute"}, {"approved": True}):
            with patch.object(self.adapter, "_dispatch") as dispatch:
                result = json.loads(self.entry("catalog").handler(bad))
            self.assertEqual(result["error"]["code"], "art_adapter_error")
            dispatch.assert_not_called()

    def test_relative_backend_import_without_sys_path_changes(self):
        # Exercise the real import path with an explicit test-only backend fixture.
        import types
        package = types.ModuleType("art_plugin_adapter_test.art_cli")
        package.__path__ = []
        api = types.ModuleType("art_plugin_adapter_test.art_cli.api")
        api.dispatch = lambda operation, arguments, *, home: {"operation": operation, "arguments": arguments, "home": str(home)}
        before = list(sys.path)
        with patch.dict(sys.modules, {package.__name__: package, api.__name__: api}):
            result = json.loads(self.entry("execute").handler({"arguments": {"x": 1}}))
        self.assertEqual(result, {"operation": "execute", "arguments": {"x": 1}, "home": str(self.home)})
        self.assertEqual(sys.path, before)


if __name__ == "__main__":
    unittest.main()
