CREATE TABLE IF NOT EXISTS ShowTypes (
    id  INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
    key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Shows (
    id          INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
    name        TEXT NOT NULL,
    name_en     TEXT,
    length      INTEGER,
    type        INTEGER NOT NULL,
    has_source  INTEGER NOT NULL DEFAULT 0,
    is_nsfw     INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    delayed     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(type) REFERENCES ShowTypes(id)
);

CREATE TABLE IF NOT EXISTS ShowNames (
    show    INTEGER NOT NULL,
    name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Aliases (
    show    INTEGER NOT NULL,
    alias   TEXT NOT NULL,
    FOREIGN KEY(show) REFERENCES Shows(id),
    UNIQUE(show, alias) ON CONFLICT IGNORE
);

CREATE TABLE IF NOT EXISTS Services (
    id          INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
    key         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 0,
    use_in_post INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Streams (
    id              INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
    service         TEXT NOT NULL,
    show            INTEGER,
    show_id         TEXT,
    show_key        TEXT NOT NULL,
    name            TEXT,
    remote_offset   INTEGER NOT NULL DEFAULT 0,
    display_offset  INTEGER NOT NULL DEFAULT 0,
    active          INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(service) REFERENCES Services(id),
    FOREIGN KEY(show) REFERENCES Shows(id)
);

CREATE TABLE IF NOT EXISTS Episodes (
    show        INTEGER NOT NULL,
    episode     INTEGER NOT NULL,
    post_url    TEXT,
    UNIQUE(show, episode) ON CONFLICT REPLACE,
    FOREIGN KEY(show) REFERENCES Shows(id)
);

CREATE TABLE IF NOT EXISTS LinkSites (
    id      INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
    key     TEXT NOT NULL UNIQUE,
    name    TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Links (
    show        INTEGER NOT NULL,
    site        INTEGER NOT NULL,
    site_key    TEXT NOT NULL,
    FOREIGN KEY(site) REFERENCES LinkSites(id),
    FOREIGN KEY(show) REFERENCES Shows(id)
);

CREATE TABLE IF NOT EXISTS Scores (
    show    INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    site    INTEGER NOT NULL,
    score   REAL NOT NULL,
    FOREIGN KEY(show) REFERENCES Shows(id),
    FOREIGN KEY(site) REFERENCES LinkSites(id)
);

CREATE TABLE IF NOT EXISTS LiteStreams (
    show           INTEGER NOT NULL,
    service         TEXT,
    service_name    TEXT NOT NULL,
    url             TEXT,
    UNIQUE(show, service) ON CONFLICT REPLACE,
    FOREIGN KEY(show) REFERENCES Shows(id)
);

CREATE TABLE IF NOT EXISTS PollSites (
    id  INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
    key TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS Polls (
    show            INTEGER NOT NULL,
    episode         INTEGER NOT NULL,
    poll_service    INTEGER NOT NULL,
    poll_id         TEXT NOT NULL,
    timestamp       INTEGER NOT NULL,
    score           REAL,
    FOREIGN KEY(show) REFERENCES Shows(id),
    FOREIGN KEY(poll_service) REFERENCES PollSites(id),
    UNIQUE(show, episode) ON CONFLICT REPLACE
);
