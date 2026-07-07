import pathlib
import sqlite3

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  path           TEXT NOT NULL UNIQUE,
  file_hash      TEXT,
  phash          TEXT,
  width          INTEGER,
  height         INTEGER,
  file_size      INTEGER,
  created_at     TEXT,
  camera_model   TEXT,
  is_screenshot  INTEGER,
  blur_score     REAL,
  dup_group      INTEGER,
  clip_labels    TEXT,
  verdict        TEXT CHECK(verdict IN ('keep','trash_candidate')) DEFAULT NULL,
  verdict_reason TEXT,
  status         TEXT NOT NULL DEFAULT 'active'
                 CHECK(status IN ('active','trashed')),
  trashed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_photos_status     ON photos(status);
CREATE INDEX IF NOT EXISTS idx_photos_verdict    ON photos(verdict);
CREATE INDEX IF NOT EXISTS idx_photos_dup_group  ON photos(dup_group);
CREATE INDEX IF NOT EXISTS idx_photos_file_hash  ON photos(file_hash);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""


def open_db(path: pathlib.Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn
