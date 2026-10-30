-- The v1 schema, kept as the baseline. Its player-name tables stop being written in v2 (names are never stored)
-- and are removed by a later migration once the owner has confirmed the data import.
CREATE TABLE IF NOT EXISTS players (
  discord_id TEXT PRIMARY KEY, username TEXT, games_played INTEGER DEFAULT 0,
  games_won INTEGER DEFAULT 0, total_points_earned INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS game_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT, played_at TEXT, channel_id TEXT, winner_id TEXT,
  player_count INTEGER, final_scores TEXT);
CREATE TABLE IF NOT EXISTS active_channels (channel_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS server_settings (guild_id TEXT PRIMARY KEY, test_mode INTEGER DEFAULT 0);
