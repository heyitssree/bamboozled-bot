"""The engine must stay pure: no I/O, no clocks, no discord, no asyncio, no global random state."""
import ast
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "bamboozled" / "engine"
FORBIDDEN_MODULES = {"discord", "asyncio", "time", "datetime", "os", "sys", "sqlite3", "aiosqlite", "httpx", "aiohttp",
                     "threading", "socket", "subprocess", "pathlib", "logging", "json", "dotenv"}


def test_no_forbidden_imports_and_no_global_random():
    problems = []
    for path in sorted(ENGINE.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]] if node.level == 0 else []
            else:
                names = []
            problems += [f"{path.name}: imports {n}" for n in names if n in FORBIDDEN_MODULES]
            # `random.random()`, `random.choice(...)` etc. use hidden global state; only random.Random is allowed
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "random"
                    and node.func.attr not in ("Random",)):
                problems.append(f"{path.name}:{node.lineno}: random.{node.func.attr}() uses global state")
            if isinstance(node, ast.Name) and node.id in ("print", "open", "input"):
                problems.append(f"{path.name}:{node.lineno}: uses {node.id}")
    assert not problems, "\n".join(problems)


def test_the_engine_does_not_import_the_legacy_game_code():
    for path in ENGINE.glob("*.py"):
        text = path.read_text()
        assert "game_engine" not in text and "cogs" not in text, path.name
