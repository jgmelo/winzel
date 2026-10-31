-- 0001: esquema inicial (SPEC, seção 6.1)

CREATE TABLE snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    kind        TEXT    NOT NULL CHECK (kind IN ('auto', 'manual')),
    is_admin    INTEGER NOT NULL CHECK (is_admin IN (0, 1))
);

CREATE TABLE check_runs (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots (id) ON DELETE CASCADE,
    check_id    TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    summary     TEXT    NOT NULL,
    duration_ms INTEGER NOT NULL,
    error       TEXT,
    PRIMARY KEY (snapshot_id, check_id)
);

CREATE TABLE items (
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots (id) ON DELETE CASCADE,
    category     TEXT    NOT NULL,
    key          TEXT    NOT NULL,
    version      TEXT,
    details_json TEXT    NOT NULL,
    PRIMARY KEY (snapshot_id, category, key)
);

CREATE TABLE metrics (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots (id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    value       REAL    NOT NULL,
    unit        TEXT    NOT NULL,
    PRIMARY KEY (snapshot_id, name)
);

CREATE TABLE milestones (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots (id),
    name        TEXT    NOT NULL UNIQUE,
    note        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);

CREATE TABLE approvals (
    category    TEXT NOT NULL,
    key         TEXT NOT NULL,
    change      TEXT NOT NULL CHECK (change IN ('added', 'removed')),
    approved_at TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (category, key, change)
);
