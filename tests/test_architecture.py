"""The architecture's first rule, checked: the engine never imports `xp`.

CLAUDE.md and notes/SPEC.md: the atmospheric engine is pure Python and testable outside
X-Plane, and only the adapter talks to the SDK. Of the adapter, only `xpio`, `plugin` and
`hud` may import `xp`; the rest say "no `xp`" in their docstrings and are tested without it.
"""
import ast
import pathlib

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "xp_gliding"
ADAPTER_WITH_XP = {"xpio.py", "plugin.py", "hud.py"}


def imports_xp(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] in ("xp", "XPLMDefs") for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "xp":
            return True
    return False


def test_the_engine_never_imports_xp():
    modules = sorted((PACKAGE / "engine").glob("*.py"))
    assert len(modules) > 10
    assert [m.name for m in modules if imports_xp(m)] == []


def test_only_three_adapter_modules_import_xp():
    found = {m.name for m in (PACKAGE / "adapter").glob("*.py") if imports_xp(m)}
    assert found == ADAPTER_WITH_XP
