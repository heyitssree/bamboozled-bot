"""Print row counts per table for one or more SQLite files (read-only).

Usage: python tools/db_report.py db/bamboozled.db [activity/backend/data/*.db ...]
"""
import sqlite3
import sys
from pathlib import Path


def report(path: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for arg in argv:
        path = Path(arg)
        if not path.is_file():
            print(f"{arg}: not found")
            continue
        print(f"{arg}:")
        counts = report(path)
        for table, n in counts.items():
            print(f"  {table:<28}{n:>10}")
        if not counts:
            print("  (no tables)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
