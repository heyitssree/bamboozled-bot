-- State that only the legacy text mode needs (orphan notices after a restart, per-server test mode).
-- Both tables go away with the text mode after cutover.
CREATE TABLE IF NOT EXISTS active_channels (channel_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS server_settings (guild_id TEXT PRIMARY KEY, test_mode INTEGER DEFAULT 0);
