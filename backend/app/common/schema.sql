
CREATE TABLE users (
 id TEXT PRIMARY KEY, username TEXT NOT NULL,
 password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0,
 created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE sessions (
 token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires DOUBLE PRECISION NOT NULL
);
CREATE TABLE configs (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 token TEXT NOT NULL, channel TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0,
 created_at DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX one_default ON configs(owner_id) WHERE is_default = 1;
CREATE TABLE nodes (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 parent_id TEXT REFERENCES nodes(id), name TEXT NOT NULL, kind TEXT NOT NULL,
 size BIGINT NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'ready',
 trash_root TEXT, deleted_at DOUBLE PRECISION, created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX sibling_name ON nodes(owner_id, coalesce(parent_id, ''), name)
 WHERE deleted_at IS NULL;
CREATE INDEX node_parent ON nodes(owner_id, parent_id);
CREATE TABLE uploads (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 node_id TEXT NOT NULL UNIQUE REFERENCES nodes(id), config_id TEXT NOT NULL REFERENCES configs(id),
 fingerprint TEXT NOT NULL, size BIGINT NOT NULL, received BIGINT NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'receiving', error TEXT, created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE blocks (
 id TEXT PRIMARY KEY, upload_id TEXT NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, size BIGINT NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'receiving',
 message_id BIGINT, sha256 TEXT, file_id TEXT, UNIQUE(upload_id, position)
);
CREATE TABLE cleanup (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 config_id TEXT NOT NULL REFERENCES configs(id), message_id BIGINT NOT NULL,
 state TEXT NOT NULL DEFAULT 'queued', error TEXT, created_at DOUBLE PRECISION NOT NULL,
 UNIQUE(config_id, message_id)
);
CREATE TABLE login_attempts (address TEXT NOT NULL, time DOUBLE PRECISION NOT NULL);
CREATE UNIQUE INDEX users_username ON users(lower(username));

CREATE TABLE shares (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
 token_hash TEXT NOT NULL UNIQUE, token_cipher TEXT NOT NULL,
 password TEXT, expires_at DOUBLE PRECISION, revoked_at DOUBLE PRECISION, created_at DOUBLE PRECISION NOT NULL,
 title TEXT NOT NULL DEFAULT '好东西'
);
CREATE INDEX shares_owner ON shares(owner_id, node_id);
CREATE TABLE share_sessions (
 token_hash TEXT PRIMARY KEY, share_id TEXT NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
 expires_at DOUBLE PRECISION NOT NULL
);

ALTER TABLE uploads ADD COLUMN origin TEXT NOT NULL DEFAULT 'browser';
CREATE TABLE offline_settings (
 id INTEGER PRIMARY KEY CHECK(id=1), concurrency INTEGER NOT NULL DEFAULT 1,
 max_bytes BIGINT NOT NULL DEFAULT 10737418240, reserve_bytes BIGINT NOT NULL DEFAULT 536870912
);
INSERT INTO offline_settings(id) VALUES (1);
CREATE TABLE offline_tasks (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 config_id TEXT NOT NULL REFERENCES configs(id), parent_id TEXT REFERENCES nodes(id) ON DELETE SET NULL,
 name TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'queued', phase TEXT NOT NULL DEFAULT 'resolve',
 downloaded BIGINT NOT NULL DEFAULT 0, total BIGINT NOT NULL DEFAULT 0,
 download_complete INTEGER NOT NULL DEFAULT 0, error TEXT,
 created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX offline_owner ON offline_tasks(owner_id,created_at);
CREATE TABLE offline_files (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES offline_tasks(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, path TEXT NOT NULL, size BIGINT NOT NULL,
 selected INTEGER NOT NULL DEFAULT 1, complete INTEGER NOT NULL DEFAULT 0,
 upload_id TEXT REFERENCES uploads(id) ON DELETE SET NULL,
 UNIQUE(task_id,position), UNIQUE(task_id,path)
);
CREATE INDEX offline_upload ON offline_files(upload_id);

CREATE INDEX login_attempt_key_time ON login_attempts(address,time);
CREATE INDEX login_attempt_time ON login_attempts(time);
