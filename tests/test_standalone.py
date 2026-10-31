# The repository must be self-contained: no reference to any other project.
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
FORBIDDEN = [r"navi", r"\bboli\b", r"BOT_INTERNAL", r"external_boli", r"user_stats", r"\.\./(?!\.)", r"NAVI_"]
SKIP = {".git", ".venv", "node_modules", "dist", "cdk.out", "__pycache__", ".pytest_cache", ".ruff_cache",
        "logs", "graphify-out", "CHANGELOG-v2.md", "docs"}
SUFFIXES = {".py", ".ts", ".tsx", ".json", ".md", ".sh", ".yml", ".yaml", ".sql", ".toml", ".txt"}
# Relative imports such as '../store/x' are normal in TypeScript, so the parent-directory pattern skips them.
PARENT_DIR_OK = {".ts", ".tsx"}


def test_no_reference_to_any_other_project():
    hits = []
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if not p.is_file() or p.name == "test_standalone.py" or set(rel.parts) & SKIP or p.suffix not in SUFFIXES:
            continue
        text = p.read_text(errors="ignore")
        for pat in FORBIDDEN:
            if pat.startswith(r"\.\.") and p.suffix in PARENT_DIR_OK:
                continue
            if re.search(pat, text, re.I):
                hits.append(f"{rel}: {pat}")
    assert not hits, "\n".join(hits)
