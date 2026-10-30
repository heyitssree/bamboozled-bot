import pytest

from bamboozled.db.migrate import migrate


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """A fresh, fully migrated database; BAMBOOZLED_DB_PATH points at it for the test."""
    path = tmp_path / "bamboozled.db"
    monkeypatch.setenv("BAMBOOZLED_DB_PATH", str(path))
    migrate(path)
    return path
