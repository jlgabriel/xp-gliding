"""The architecture's rules, checked: the engine and `nav/` never import `xp`, and the Flight
Computer reads nothing of where the thermals are.

The project's design rule: the atmospheric engine is pure Python and testable outside
X-Plane, and only the adapter talks to the SDK. Of the adapter, only `xpio`, `plugin`, `hud` and
`computer` may import `xp`; the rest say "no `xp`" in their docstrings and are tested without it.
`nav/` is to the Flight Computer what `engine/` is to the thermals, and the Flight Computer shows
what the glider can observe: neither `nav/` nor `adapter/computer.py` may read the engine's field,
its thermals, clouds, markers or hotspots.
"""
import ast
import pathlib

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "xp_gliding"
ADAPTER_WITH_XP = {"xpio.py", "plugin.py", "hud.py", "computer.py"}
# The engine's modules that know where the thermals are, or what they look like.
ENGINE_KNOWS_THERMALS = {"field", "updraft", "clouds", "markers", "hotspots", "areas", "airstart"}


def imports_xp(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] in ("xp", "XPLMDefs") for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "xp":
            return True
    return False


def engine_imports(path):
    """The engine modules a module of the package imports, by their names under `engine`."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            parts = (node.module or "").split(".")
            if "engine" in parts:
                rest = parts[parts.index("engine") + 1:]
                found |= {rest[0]} if rest else {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if "engine" in parts:
                    found.add(".".join(parts[parts.index("engine") + 1:]) or "engine")
    return found


def test_the_engine_never_imports_xp():
    modules = sorted((PACKAGE / "engine").glob("*.py"))
    assert len(modules) > 10
    assert [m.name for m in modules if imports_xp(m)] == []


def test_nav_never_imports_xp_nor_the_engine():
    modules = sorted((PACKAGE / "nav").glob("*.py"))
    assert modules
    assert [m.name for m in modules if imports_xp(m)] == []
    assert {m.name: engine_imports(m) for m in modules if engine_imports(m)} == {}


def test_the_flight_computer_reads_nothing_of_the_thermals():
    assert engine_imports(PACKAGE / "adapter" / "computer.py") & ENGINE_KNOWS_THERMALS == set()


def test_only_four_adapter_modules_import_xp():
    found = {m.name for m in (PACKAGE / "adapter").glob("*.py") if imports_xp(m)}
    assert found == ADAPTER_WITH_XP
