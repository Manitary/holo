CREATE TABLE IF NOT EXISTS ShowTypes (
    id  INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Shows (
    id          INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    name_en     TEXT,
    length      INTEGER DEFAULT 0,
    type        INTEGER NOT NULL,
    has_source  INTEGER NOT NULL DEFAULT 0,
    is_nsfw     INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    delayed     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(type) REFERENCES ShowTypes(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS ShowNames (
    show    INTEGER NOT NULL,
    name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS Aliases (
    show    INTEGER NOT NULL,
    alias   TEXT NOT NULL,
    UNIQUE(show, alias) ON CONFLICT IGNORE,
    FOREIGN KEY(show) REFERENCES Shows(id)
);

CREATE TABLE IF NOT EXISTS Services (
    id          INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 0,
    use_in_post INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Streams (
    id              INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    service         INTEGER NOT NULL,
    show            INTEGER NOT NULL,
    show_id         TEXT,
    show_key        TEXT NOT NULL,
    name            TEXT,
    remote_offset   INTEGER NOT NULL DEFAULT 0,
    display_offset  INTEGER NOT NULL DEFAULT 0,
    active          INTEGER NOT NULL DEFAULT 1,
    UNIQUE(service, show),
    FOREIGN KEY(service) REFERENCES Services(id) ON UPDATE CASCADE,
    FOREIGN KEY(show) REFERENCES Shows(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS Episodes (
    show        INTEGER NOT NULL,
    episode     INTEGER NOT NULL,
    post_url    TEXT,
    UNIQUE(show, episode) ON CONFLICT REPLACE,
    FOREIGN KEY(show) REFERENCES Shows(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS LinkSites (
    id      INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    key     TEXT NOT NULL UNIQUE,
    name    TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS Links (
    show        INTEGER NOT NULL,
    site        INTEGER NOT NULL,
    site_key    TEXT NOT NULL,
    UNIQUE(show, site) ON CONFLICT IGNORE,
    FOREIGN KEY(site) REFERENCES LinkSites(id) ON UPDATE CASCADE,
    FOREIGN KEY(show) REFERENCES Shows(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS Scores (
    show    INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    site    INTEGER NOT NULL,
    score   REAL NOT NULL,
    UNIQUE(show, episode, site) ON CONFLICT REPLACE,
    FOREIGN KEY(show) REFERENCES Shows(id) ON UPDATE CASCADE,
    FOREIGN KEY(site) REFERENCES LinkSites(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS LiteStreams (
    show            INTEGER NOT NULL,
    service         TEXT NOT NULL,
    service_name    TEXT NOT NULL,
    url             TEXT,
    UNIQUE(show, service) ON CONFLICT REPLACE,
    FOREIGN KEY(show) REFERENCES Shows(id) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS PollSites (
    id  INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS Polls (
    show            INTEGER NOT NULL,
    episode         INTEGER NOT NULL,
    poll_service    INTEGER NOT NULL,
    poll_id         TEXT NOT NULL,
    timestamp       INTEGER NOT NULL,
    score           REAL,
    UNIQUE(show, episode, poll_service) ON CONFLICT REPLACE,
    FOREIGN KEY(show) REFERENCES Shows(id) ON UPDATE CASCADE,
    FOREIGN KEY(poll_service) REFERENCES PollSites(id) ON UPDATE CASCADE
);
