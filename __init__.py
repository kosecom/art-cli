"""Native Hermes entry point; deliberately inert until a tool is called.

Hermes loads this directory as a namespaced package. Relative imports keep
its bundled backend private without modifying sys.path or core modules.
"""
from __future__ import annotations

import json


_DESCRIPTIONS = {
    "catalog": "List all 13 native ArtCraft applications and cached capabilities without starting an app. Use operation doctor for diagnostics or refresh for explicitly requested native tool and editor-command rediscovery.",
    "native": "Use the complete vendor CLI surface for a discovered creative application. First consult art_guide and native help. Only discovered binaries and operator-configured modes are allowed; do not invent approval or authentication.",
    "rpc": "Use native ArtCraft MCP resources/prompts, or set arguments.transport=control to invoke any source-supported GUI method on the operator-bound local connection. Supply app, method, params. Inspect art_guide first; no endpoint or credential override, implicit GUI launch or automatic callback approval.",
    "search": "Search native ArtCraft MCP tools and nested editor commands; scope tools, commands or all. Results are paginated. Discover candidates before requesting exact schemas with art_describe.",
    "describe": "Get the exact live native command schema and requirements before execution. Forward backend arguments exactly as returned by catalog/search.",
    "execute": "Execute a described native creative application command with its exact arguments. Preserve user approval requirements; never invent or auto-approve callbacks. Returns the native result including errors and images.",
    "batch": "Execute a batch of described native commands. Supply backend batch arguments exactly; each action retains its native approval requirements and result.",
    "guide": "Read ART-CLI usage and backend argument conventions. Start here when unsure how to construct catalog, search, describe, execute, or batch arguments.",
}


def _dispatch(operation, arguments, *, home):
    # Delayed relative import: no application discovery or backend startup in register().
    from .art_cli.api import dispatch
    return dispatch(operation, arguments, home=home)


def _handler(operation):
    def handle(args: dict, **kwargs) -> str:
        # kwargs is Hermes invocation context, NOT user backend parameters or consent.
        try:
            if not isinstance(args, dict):
                raise TypeError("Tool arguments must be an object")
            unexpected = set(args) - ({"arguments", "operation"} if operation == "catalog" else {"arguments"})
            if unexpected:
                raise ValueError("Unknown tool envelope fields: " + ", ".join(sorted(unexpected)))
            selected = args.get("operation", "catalog") if operation == "catalog" else operation
            if operation == "catalog" and selected not in ("catalog", "doctor", "refresh"):
                raise ValueError("art_catalog operation must be catalog, doctor, or refresh")
            arguments = args.get("arguments", {})
            if not isinstance(arguments, dict):
                raise TypeError("arguments must be an object")
            # Resolve every call, not at registration: a process may serve many profiles.
            from hermes_constants import get_hermes_home
            result = _dispatch(selected, arguments, home=get_hermes_home())
            if not isinstance(result, dict):
                raise TypeError("ART-CLI dispatch must return a dict")
            # Native general-plugin handlers return JSON strings. No result wrapping,
            # truncation, str(dict), error swallowing, or image-field removal.
            return json.dumps(result, ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": {"code": "art_adapter_error", "type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False)
    return handle


def register(ctx):
    """Register eight small progressive tools through Hermes' supported facade."""
    for operation, description in _DESCRIPTIONS.items():
        name = "art_" + operation
        properties = {
            "arguments": {"type": "object", "description": "Arguments for the backend operation, following art_guide and live command schemas.", "additionalProperties": True},
        }
        if operation == "catalog":
            properties["operation"] = {"type": "string", "enum": ["catalog", "doctor", "refresh"], "default": "catalog"}
        ctx.register_tool(
            name=name,
            toolset="art-cli",
            schema={"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "additionalProperties": False}},
            handler=_handler(operation),
            description=description,
        )
