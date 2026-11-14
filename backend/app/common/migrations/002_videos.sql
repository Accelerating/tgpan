CREATE TABLE video_cookies (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, domain TEXT NOT NULL, secret TEXT NOT NULL,
 created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX video_cookies_owner ON video_cookies(owner_id);
CREATE TABLE video_tasks (
 task_id TEXT PRIMARY KEY REFERENCES offline_tasks(id) ON DELETE CASCADE,
 cookie_id TEXT REFERENCES video_cookies(id) ON DELETE SET NULL,
 quality TEXT NOT NULL DEFAULT 'best', audio_only INTEGER NOT NULL DEFAULT 0,
 collection_title TEXT NOT NULL DEFAULT ''
);
CREATE TABLE video_entries (
 id TEXT PRIMARY KEY, task_id TEXT REFERENCES video_tasks(task_id) ON DELETE SET NULL,
 owner_id TEXT NOT NULL REFERENCES users(id), position INTEGER NOT NULL,
 source TEXT NOT NULL, metadata TEXT NOT NULL,
 file_id TEXT REFERENCES offline_files(id) ON DELETE SET NULL,
 node_id TEXT REFERENCES nodes(id) ON DELETE CASCADE,
 UNIQUE(task_id,position)
);
CREATE INDEX video_entries_node ON video_entries(node_id);
