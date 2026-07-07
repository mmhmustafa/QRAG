"""Startup backups: rolling snapshots of the SQLite database."""
from app.services import backup_sqlite_database

def test_backup_creates_rolling_snapshots(tmp_path):
    db=tmp_path/"questionnaire.db";db.write_bytes(b"answer data")
    url=f"sqlite:///{db.as_posix()}"
    made=[backup_sqlite_database(url,keep=3) for _ in range(5)]
    assert all(x is not None for x in made)
    backups=sorted((tmp_path/"backups").glob("questionnaire-*.db"))
    assert len(backups)==3  # oldest snapshots pruned
    assert backups[-1].read_bytes()==b"answer data"

def test_backup_skips_non_sqlite_and_missing_files(tmp_path):
    assert backup_sqlite_database("postgresql://localhost/app") is None
    assert backup_sqlite_database(f"sqlite:///{(tmp_path/'missing.db').as_posix()}") is None
