-- Names and avatars are NEVER stored: they are resolved from Discord at display time. Only ids and results persist.
-- (schema_version is created by the runner.)
CREATE TABLE matches (
  match_id     TEXT PRIMARY KEY,
  mode         TEXT NOT NULL CHECK (mode IN ('bamboozled', 'fff', 'survival')),
  guild_id     INTEGER NOT NULL,
  started_at   TEXT NOT NULL,
  ended_at     TEXT,
  rounds       INTEGER,
  difficulty   TEXT,
  category     TEXT,
  player_count INTEGER NOT NULL
);
CREATE TABLE match_results (
  match_id TEXT NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
  user_id  INTEGER NOT NULL,
  rank     INTEGER NOT NULL,
  score    INTEGER NOT NULL,
  correct  INTEGER NOT NULL DEFAULT 0,
  details  TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (match_id, user_id)
) WITHOUT ROWID;
CREATE INDEX ix_results_user ON match_results(user_id);
CREATE TABLE stats (
  user_id INTEGER NOT NULL,
  mode TEXT NOT NULL,
  games INTEGER NOT NULL DEFAULT 0,
  wins INTEGER NOT NULL DEFAULT 0,
  best_score INTEGER NOT NULL DEFAULT 0,
  total_score INTEGER NOT NULL DEFAULT 0,
  best_streak INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, mode)
) WITHOUT ROWID;
CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_by INTEGER,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
