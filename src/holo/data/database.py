from __future__ import annotations

import logging
import re
import sqlite3
from datetime import UTC, datetime
from functools import lru_cache, singledispatchmethod, wraps
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

from unidecode import unidecode

from ..services import AbstractInfoHandler, AbstractPollHandler, AbstractServiceHandler
from .models import (
    Episode,
    EpisodeScore,
    Link,
    LinkSite,
    LiteStream,
    Poll,
    PollSite,
    Service,
    Show,
    ShowType,
    Stream,
    UnprocessedShow,
    UnprocessedStream,
)

logger = logging.getLogger(__name__)

QUERY_PATH = Path() / "holo" / "data"

P = ParamSpec("P")
T = TypeVar("T")
T0 = TypeVar("T0")


def living_in(the_database: str) -> DatabaseDatabase | None:
    """
    wow wow
    :param the_database:
    :return:
    """
    try:
        return DatabaseDatabase(the_database)
    except sqlite3.OperationalError:
        logger.error("Failed to open database, %s", the_database)
        return None


def get_query(query_name: str) -> str:
    path = QUERY_PATH / f"{query_name}.sql"
    with path.open() as f:
        query = f.read()
    return query


# Database


def db_error(f: Callable[P, Any]) -> Callable[P, bool]:
    @wraps(f)
    def protected(*args: P.args, **kwargs: P.kwargs) -> bool:
        try:
            f(*args, **kwargs)
            return True
        except Exception as e:
            logger.exception("Database exception thrown: %s", e)
            return False

    return protected


def db_error_default(
    default_value: T0,
) -> Callable[[Callable[P, T]], Callable[P, T | T0]]:
    value = default_value

    def decorate(f: Callable[P, T]) -> Callable[P, T | T0]:
        @wraps(wrapped=f)
        def protected(*args: P.args, **kwargs: P.kwargs) -> T | T0:
            nonlocal value
            try:
                return f(*args, **kwargs)
            except Exception as e:
                logger.exception("Database exception thrown: %s", e)
                return value

        return protected

    return decorate


class DatabaseDatabase(sqlite3.Connection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.row_factory = sqlite3.Row
        self.execute("PRAGMA foreign_keys=ON")
        self.create_collation("alphanum", _collate_alphanum)

    # Setup
    def setup_tables(self) -> None:
        self.executescript(get_query("create_tables"))
        self.executemany(
            "INSERT OR IGNORE INTO ShowTypes (id, key) VALUES (?, ?)",
            [(t.value, t.name.lower()) for t in ShowType],
        )
        self.commit()

    def register_services(self, services: dict[str, AbstractServiceHandler]) -> None:
        self.execute("UPDATE Services SET enabled = 0")
        for service_key in services:
            service = services[service_key]
            self.execute(
                "INSERT OR IGNORE INTO Services (key, name) VALUES (?, '')",
                (service.key,),
            )
            self.execute(
                "UPDATE Services SET name = ?, enabled = 1 WHERE key = ?",
                (service.name, service.key),
            )
        self.commit()

    def register_link_sites(self, sites: dict[str, AbstractInfoHandler]) -> None:
        self.execute("UPDATE LinkSites SET enabled = 0")
        for site_key in sites:
            site = sites[site_key]
            self.execute(
                "INSERT OR IGNORE INTO LinkSites (key, name) VALUES (?, '')",
                (site.key,),
            )
            self.execute(
                "UPDATE LinkSites SET name = ?, enabled = 1 WHERE key = ?",
                (site.name, site.key),
            )
        self.commit()

    def register_poll_sites(self, polls: dict[str, AbstractPollHandler]) -> None:
        for poll_key in polls:
            poll = polls[poll_key]
            self.execute(
                "INSERT OR IGNORE INTO PollSites (key) VALUES (?)", (poll.key,)
            )
        self.commit()

    # Services
    @db_error_default(None)
    @lru_cache(10)
    def get_service_from_id(self, service_id: int | None = None) -> Service | None:
        if not service_id:
            logger.error("ID or key required to get service")
            return None
        q = self.execute(
            "SELECT id, key, name, enabled, use_in_post FROM Services WHERE id = ?",
            (service_id,),
        )
        return Service(**q.fetchone())

    @db_error_default(None)
    @lru_cache(10)
    def get_service_from_key(self, key: str | None = None) -> Service | None:
        if not key:
            logger.error("ID or key required to get service")
            return None
        q = self.execute(
            "SELECT id, key, name, enabled, use_in_post FROM Services WHERE key = ?",
            (key,),
        )
        return Service(**q.fetchone())

    @db_error_default(cast(list[Service], []))
    def get_services(self, enabled: bool = True) -> list[Service]:
        services: list[Service] = []
        q = self.execute(
            "SELECT id, key, name, enabled, use_in_post FROM Services WHERE enabled = ?",
            (1 if enabled else 0,),
        )
        for service in q.fetchall():
            services.append(Service(**service))
        return services

    @db_error_default(None)
    def get_stream(
        self, service_tuple: tuple[Service, str] | None = None
    ) -> Stream | None:
        if not service_tuple:
            logger.error("Nothing provided to get stream")
            return None
        service, show_key = service_tuple
        logger.debug("Getting stream for %s/%s", service, show_key)
        q = self.execute(
            """SELECT
            id, service, show, show_id, show_key, name, remote_offset, display_offset, active
            FROM Streams
            WHERE service = ?
            AND show_key = ?""",
            (service.id, show_key),
        )
        stream = q.fetchone()
        if stream is None:
            logger.error("Stream %s not found", service_tuple)
            return None
        return self._make_stream_from_query(stream)

    @db_error_default(cast(list[Stream], []))
    def get_active_streams_for_service(
        self, service: Service | None = None
    ) -> list[Stream]:
        if not service:
            logger.error("A service must be provided to get streams")
            return []
        service = self.get_service_from_key(key=service.key)
        if not service:
            logger.error("Could not get service from its own key")
            return []

        logger.debug("Getting all active streams for service %s", service.key)
        q = self.execute(
            """SELECT
            st.id, st.service, st.show, st.show_id, st.show_key,
            st.name, st.remote_offset, st.display_offset, st.active
            FROM Streams st JOIN Shows sh ON st.show = sh.id
            WHERE st.service = ?
            AND st.active = 1
            AND sh.enabled = 1""",
            (service.id,),
        )
        streams = list(
            filter(
                None, [self._make_stream_from_query(stream) for stream in q.fetchall()]
            )
        )
        return streams

    @db_error_default(cast(list[Stream], []))
    def get_streams_for_show(
        self, show: Show | None = None, active: bool = True
    ) -> list[Stream]:
        if not show:
            logger.error("A show must be provided to get streams")
            return []
        if active:
            logger.debug("Getting all active streams for show %s", show.id)
            q = self.execute(
                """SELECT
                id, service, show, show_id, show_key, name, remote_offset, display_offset, active
                FROM Streams
                WHERE show = ?
                AND active = 1
                AND (SELECT enabled FROM Shows WHERE id = show) = 1""",
                (show.id,),
            )
        else:
            logger.debug("Getting all inactive streams for show %s", show.id)
            q = self.execute(
                """SELECT
                id, service, show, show_id, show_key, name, remote_offset, display_offset, active
                FROM Streams
                WHERE show = ? AND active = 0""",
                (show.id,),
            )
        streams = list(
            filter(
                None, [self._make_stream_from_query(stream) for stream in q.fetchall()]
            )
        )
        return streams

    @db_error_default(cast(list[Stream], []))
    def get_unmatched_streams(self) -> list[Stream]:
        logger.debug("Getting unmatched streams")
        q = self.execute(
            """SELECT
            id, service, show, show_id, show_key, name, remote_offset, display_offset, active
            FROM Streams
            WHERE show IS NULL"""
        )
        streams = list(
            filter(
                None, [self._make_stream_from_query(stream) for stream in q.fetchall()]
            )
        )
        return streams

    @db_error_default(cast(list[Stream], []))
    def get_streams_missing_name(
        self,
        active: bool = True,
    ) -> list[Stream]:
        if active:
            logger.debug("Getting all active streams missing show name")
            q = self.execute(
                """SELECT
                id, service, show, show_id, show_key, name, remote_offset, display_offset, active
                FROM Streams
                WHERE (name IS NULL OR name = '')
                AND active = 1
                AND (SELECT enabled FROM Shows WHERE id = show) = 1"""
            )
        else:
            logger.debug("Getting all inactive streams missing show name")
            q = self.execute(
                """SELECT
                id, service, show, show_id, show_key, name, remote_offset, display_offset, active
                FROM Streams
                WHERE (name IS NULL OR name = '') AND active = 0"""
            )
        streams = list(
            filter(
                None, [self._make_stream_from_query(stream) for stream in q.fetchall()]
            )
        )
        return streams

    @db_error_default(False)
    def has_stream(self, service_key: str, key: str) -> bool:
        service = self.get_service_from_key(key=service_key)
        if not service:
            return False
        q = self.execute(
            "SELECT count(*) FROM Streams WHERE service = ? AND show_key = ?",
            (service.id, key),
        )
        return q.fetchone()["count(*)"] > 0

    @db_error
    def add_stream(
        self, raw_stream: UnprocessedStream, show_id: int | None, commit: bool = True
    ) -> None:
        logger.debug("Inserting stream: %s", raw_stream)

        service = self.get_service_from_key(key=raw_stream.service_key)
        if not service:
            logger.debug("Cannot get service from key: %s", raw_stream.service_key)
            return None
        self.execute(
            """INSERT INTO Streams
            (service, show, show_id, show_key, name, remote_offset, display_offset, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                service.id,
                show_id,
                raw_stream.show_id,
                raw_stream.show_key,
                raw_stream.name,
                raw_stream.remote_offset,
                raw_stream.display_offset,
                show_id is not None,
            ),
        )
        if commit:
            self.commit()

    @db_error
    def update_stream(
        self,
        stream: Stream,
        show: int | None = None,
        active: bool | int | None = None,
        name: str | None = None,
        show_id: int | None = None,
        show_key: str | None = None,
        remote_offset: int | None = None,
        commit: bool = True,
    ) -> None:
        logger.debug("Updating stream: id=%s", stream.id)
        if show:
            self.execute("UPDATE Streams SET show = ? WHERE id = ?", (show, stream.id))
        if active:
            self.execute(
                "UPDATE Streams SET active = ? WHERE id = ?", (active, stream.id)
            )
        if name:
            self.execute("UPDATE Streams SET name = ? WHERE id = ?", (name, stream.id))
        if show_id:
            self.execute(
                "UPDATE Streams SET show_id = ? WHERE id = ?", (show_id, stream.id)
            )
        if show_key:
            self.execute(
                "UPDATE Streams SET show_key = ? WHERE id = ?", (show_key, stream.id)
            )
        if remote_offset:
            self.execute(
                "UPDATE Streams SET remote_offset = ? WHERE id = ?",
                (remote_offset, stream.id),
            )

        if commit:
            self.commit()

    # Infos
    @db_error_default(cast(list[LiteStream], []))
    def get_lite_streams_from_show(
        self,
        show: Show | None = None,
    ) -> list[LiteStream]:
        if not show:
            logger.error("A service or show must be provided to get lite streams")
            return []
        logger.debug("Getting all lite streams for show %s", show)
        q = self.execute(
            "SELECT show, service, service_name, url FROM LiteStreams \
                        WHERE show = ?",
            (show.id,),
        )
        return [LiteStream(**lite_stream) for lite_stream in q.fetchall()]

    @db_error
    def add_lite_stream(
        self, show: int | None, service: str, service_name: str, url: str
    ) -> None:
        logger.debug("Inserting lite stream %s (%s) for show %s", service, url, show)
        self.execute(
            "INSERT INTO LiteStreams (show, service, service_name, url) values (?, ?, ?, ?)",
            (show, service, service_name, url),
        )
        self.commit()

    # Links
    @db_error_default(None)
    def get_link_site_from_id(self, site_id: str | None = None) -> LinkSite | None:
        if not site_id:
            logger.error("ID required to get link site")
            return None
        q = self.execute(
            "SELECT id, key, name, enabled FROM LinkSites WHERE id = ?", (site_id,)
        )
        site = q.fetchone()
        if not site:
            return None
        return LinkSite(**site)

    @db_error_default(None)
    def get_link_site_from_key(self, key: str | None = None) -> LinkSite | None:
        if not key:
            logger.error("ID or key required to get link site")
            return None
        q = self.execute(
            "SELECT id, key, name, enabled FROM LinkSites WHERE key = ?", (key,)
        )
        site = q.fetchone()
        if not site:
            return None
        return LinkSite(**site)

    @db_error_default(cast(list[LinkSite], []))
    def get_link_sites(self, enabled: bool = True) -> list[LinkSite]:
        q = self.execute(
            "SELECT id, key, name, enabled FROM LinkSites WHERE enabled = ?",
            (1 if enabled else 0,),
        )
        return [LinkSite(**link) for link in q.fetchall()]

    @db_error_default(cast(list[Link], []))
    def get_links(self, show: Show | None = None) -> list[Link]:
        if not show:
            logger.error("A show must be provided to get links")
            return []
        logger.debug("Getting all links for show %s", show.id)

        # Get all streams with show ID
        q = self.execute(
            "SELECT site, show, site_key FROM Links WHERE show = ?", (show.id,)
        )
        return [Link(**link) for link in q.fetchall()]

    @db_error_default(None)
    def get_link(self, show: Show, link_site: LinkSite) -> Link | None:
        logger.debug("Getting link for show %s and site %s", show.id, link_site.key)

        q = self.execute(
            "SELECT site, show, site_key FROM Links WHERE show = ? AND site = ?",
            (show.id, link_site.id),
        )
        link = q.fetchone()
        if not link:
            return None
        return Link(**link)

    @db_error_default(False)
    def has_link(self, site_key: str, key: str, show: int | None = None) -> bool:
        site = self.get_link_site_from_key(key=site_key)
        if not site:
            return False
        if show:
            q = self.execute(
                "SELECT count(*) FROM Links WHERE site = ? AND site_key = ? AND show = ?",
                (site.id, key, show),
            )
        else:
            q = self.execute(
                "SELECT count(*) FROM Links WHERE site = ? AND site_key = ?",
                (site.id, key),
            )
        return q.fetchone()["count(*)"] > 0

    @db_error
    def add_link(
        self, raw_show: UnprocessedShow, show_id: int, commit: bool = True
    ) -> None:
        logger.debug("Inserting link: %s/%s", show_id, raw_show)

        site = self.get_link_site_from_key(key=raw_show.site_key)
        if not site:
            logger.error('  Invalid site "%s"', raw_show.site_key)
            return
        site_key = raw_show.show_key

        self.execute(
            "INSERT INTO Links (show, site, site_key) VALUES (?, ?, ?)",
            (show_id, site.id, site_key),
        )
        if commit:
            self.commit()

    # Shows
    @db_error_default(cast(list[Show], []))
    def get_shows_missing_length(self, enabled: bool = True) -> list[Show]:
        q = self.execute(
            """SELECT
            id, name, name_en, length, type AS show_type, has_source, is_nsfw, enabled, delayed
            FROM Shows
            WHERE (length IS NULL OR length = '' OR length = 0) AND enabled = ?""",
            (enabled,),
        )
        return [self._make_show_from_query(show) for show in q.fetchall()]

    @db_error_default(cast(list[Show], []))
    def get_shows_missing_stream(self, enabled: bool = True) -> list[Show]:
        q = self.execute(
            """SELECT
            id, name, name_en, length, type AS show_type, has_source, is_nsfw, enabled, delayed
            FROM Shows show
            WHERE (
                SELECT count(*)
                FROM Streams stream, Services service
                WHERE stream.show = show.id
                AND stream.active = 1
                AND stream.service = service.id
                AND service.enabled = 1
            ) = 0
            AND enabled = ?""",
            (enabled,),
        )
        return [self._make_show_from_query(show) for show in q.fetchall()]

    @db_error_default(cast(list[Show], []))
    def get_shows_delayed(self, enabled: bool = True) -> list[Show]:
        q = self.execute(
            """SELECT
            id, name, name_en, length, type AS show_type, has_source, is_nsfw, enabled, delayed
            FROM Shows
            WHERE delayed = 1 AND enabled = ?""",
            (enabled,),
        )
        return [self._make_show_from_query(show) for show in q.fetchall()]

    @db_error_default(cast(list[Show], []))
    def get_shows_by_enabled_status(self, enabled: bool) -> list[Show]:
        q = self.execute(
            """SELECT
            id, name, name_en, length, type AS show_type, has_source, is_nsfw, enabled, delayed
            FROM Shows
            WHERE enabled = ?""",
            (enabled,),
        )
        return [self._make_show_from_query(show) for show in q.fetchall()]

    @singledispatchmethod
    def get_show(self, arg: int | Stream | None) -> Show | None:
        if not arg:
            logger.error("Show ID or stream not provided to get_show")

    @db_error_default(None)
    @get_show.register
    def _(self, arg: int) -> Show | None:
        q = self.execute(
            """SELECT
            id, name, name_en, length, type AS show_type, has_source, is_nsfw, enabled, delayed
            FROM Shows
            WHERE id = ?""",
            (arg,),
        )
        show = q.fetchone()
        if not show:
            return None
        return self._make_show_from_query(show)

    @db_error_default(None)
    @get_show.register
    def _(self, arg: Stream) -> Show | None:
        show_id = arg.show.id
        return self.get_show(show_id)

    @db_error_default(None)
    def get_show_by_name(self, name: str) -> Show | None:
        # logger.debug("Getting show from database")

        q = self.execute(
            """SELECT
            id, name, name_en, length, type AS show_type, has_source, is_nsfw, enabled, delayed
            FROM Shows
            WHERE name = ?""",
            (name,),
        )
        show = q.fetchone()
        if not show:
            return None
        return self._make_show_from_query(show)

    @db_error_default(cast(list[str], []))
    def get_aliases(self, show: Show) -> list[str]:
        q = self.execute("SELECT alias FROM Aliases WHERE show = ?", (show.id,))
        return [s["alias"] for s in q.fetchall()]

    @db_error_default(None)
    def add_show(self, raw_show: UnprocessedShow, commit: bool = True) -> int | None:
        logger.debug("Inserting show: %s", raw_show)

        name = raw_show.name
        name_en = raw_show.name_en
        length = raw_show.episode_count
        show_type = from_show_type(raw_show.show_type)
        has_source = raw_show.has_source
        is_nsfw = raw_show.is_nsfw
        show_id = self.execute(
            """INSERT INTO Shows
            (name, name_en, length, type, has_source, is_nsfw)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (name, name_en, length, show_type, has_source, is_nsfw),
        ).lastrowid
        self.add_show_names(
            raw_show.name, *raw_show.more_names, show_id=show_id, commit=commit
        )

        if commit:
            self.commit()
        return show_id

    @db_error
    def add_alias(self, show_id: int, alias: str, commit: bool = True) -> None:
        self.execute(
            "INSERT INTO Aliases (show, alias) VALUES (?, ?)", (show_id, alias)
        )
        if commit:
            self.commit()

    @db_error_default(None)
    def update_show(
        self, show_id: str, raw_show: UnprocessedShow, commit: bool = True
    ) -> None:
        logger.debug("Updating show: %s", raw_show.name)

        # name = raw_show.name
        name_en = raw_show.name_en
        length = raw_show.episode_count
        show_type = from_show_type(raw_show.show_type)
        has_source = raw_show.has_source
        is_nsfw = raw_show.is_nsfw

        if name_en:
            self.execute(
                "UPDATE Shows SET name_en = ? WHERE id = ?", (name_en, show_id)
            )
        if length:
            self.execute("UPDATE Shows SET length = ? WHERE id = ?", (length, show_id))
        self.execute(
            "UPDATE Shows SET type = ?, has_source = ?, is_nsfw = ? WHERE id = ?",
            (show_type, has_source, is_nsfw, show_id),
        )

        if commit:
            self.commit()

    @db_error
    def add_show_names(
        self, *names: str, show_id: int | None = None, commit: bool = True
    ) -> None:
        self.executemany(
            "INSERT INTO ShowNames (show, name) VALUES (?, ?)",
            [(show_id, name) for name in names],
        )
        if commit:
            self.commit()

    @db_error
    def set_show_episode_count(self, show: Show, length: int) -> None:
        logger.debug(
            "Updating show episode count in database: %s, %d", show.name, length
        )
        self.execute("UPDATE Shows SET length = ? WHERE id = ?", (length, show.id))
        self.commit()

    @db_error
    def set_show_delayed(self, show: Show, delayed: bool = True) -> None:
        logger.debug("Marking show %s as delayed: %s", show.name, delayed)
        self.execute("UPDATE Shows SET delayed = ? WHERE id = ?", (delayed, show.id))
        self.commit()

    @db_error
    def set_show_enabled(
        self, show: Show, enabled: bool = True, commit: bool = True
    ) -> None:
        logger.debug(
            "Marking show %s as %s", show.name, "enabled" if enabled else "disabled"
        )
        self.execute("UPDATE Shows SET enabled = ? WHERE id = ?", (enabled, show.id))
        if commit:
            self.commit()

    # Episodes
    @db_error_default(True)
    def stream_has_episode(self, stream: Stream, episode_num: int) -> bool:
        q = self.execute(
            "SELECT count(*) FROM Episodes WHERE show = ? AND episode = ?",
            (stream.show, episode_num),
        )
        num_found = q.fetchone()["count(*)"]
        logger.debug(
            "Found %d entries matching show %s, episode %d",
            num_found,
            stream.show,
            episode_num,
        )
        return num_found > 0

    @db_error_default(None)
    def get_latest_episode(self, show: Show) -> Episode | None:
        q = self.execute(
            """SELECT episode AS number, post_url AS link
            FROM Episodes
            WHERE show = ?
            ORDER BY episode DESC
            LIMIT 1""",
            (show.id,),
        )
        data = q.fetchone()
        if not data:
            return None
        return Episode(**data)

    @db_error
    def add_episode(self, show: Show, episode_num: int, post_url: str) -> None:
        logger.debug(
            "Inserting episode %d for show %s (%s)", episode_num, show.id, post_url
        )
        self.execute(
            "INSERT INTO Episodes (show, episode, post_url) VALUES (?, ?, ?)",
            (show.id, episode_num, post_url),
        )
        self.commit()

    @db_error_default(cast(list[Episode], []))
    def get_episodes(self, show: Show, ensure_sorted: bool = True) -> list[Episode]:
        q = self.execute(
            "SELECT episode AS number, post_url AS link FROM Episodes WHERE show = ?",
            (show.id,),
        )
        episodes = [Episode(**data) for data in q.fetchall()]
        if ensure_sorted:
            episodes = sorted(episodes, key=lambda e: e.number)
        return episodes

    # Scores
    @db_error_default(cast(list[EpisodeScore], []))
    def get_show_scores(self, show: Show) -> list[EpisodeScore]:
        q = self.execute(
            "SELECT episode, site AS site_id, score FROM Scores WHERE show=?",
            (show.id,),
        )
        return [EpisodeScore(show_id=show.id, **s) for s in q.fetchall()]

    @db_error_default(cast(list[EpisodeScore], []))
    def get_episode_scores(self, show: Show, episode: Episode) -> list[EpisodeScore]:
        q = self.execute(
            "SELECT site AS site_id, score FROM Scores WHERE show=? AND episode=?",
            (show.id, episode.number),
        )
        return [
            EpisodeScore(show_id=show.id, episode=episode.number, **s)
            for s in q.fetchall()
        ]

    @db_error_default(None)
    def get_episode_score_avg(
        self, show: Show, episode: Episode
    ) -> EpisodeScore | None:
        logger.debug("Calculating avg score for %s (%s)", show.name, show.id)
        q = self.execute(
            "SELECT score FROM Scores WHERE show=? AND episode=?",
            (show.id, episode.number),
        )
        scores = [s["score"] for s in q.fetchall()]
        if not scores:
            return None
        score = sum(scores) / len(scores)
        logger.debug("  Score: %f (from %d scores)", score, len(scores))
        return EpisodeScore(show_id=show.id, episode=episode.number, score=score)

    @db_error
    def add_episode_score(
        self,
        show: Show,
        episode: Episode,
        site: LinkSite,
        score: float,
        commit: bool = True,
    ) -> None:
        self.execute(
            "INSERT INTO Scores (show, episode, site, score) VALUES (?, ?, ?, ?)",
            (show.id, episode.number, site.id, score),
        )
        if commit:
            self.commit()

    # Polls

    @db_error_default(None)
    def get_poll_site(
        self, poll_site_id: int | None = None, key: str | None = None
    ) -> PollSite | None:
        if poll_site_id:
            q = self.execute(
                "SELECT id, key FROM PollSites WHERE id = ?", (poll_site_id,)
            )
        elif key:
            q = self.execute("SELECT id, key FROM PollSites WHERE key = ?", (key,))
        else:
            logger.error("ID or key required to get poll site")
            return None
        site = q.fetchone()
        if not site:
            return None
        return PollSite(**site)

    @db_error
    def add_poll(
        self,
        show: Show,
        episode: Episode,
        site: PollSite,
        poll_id: str,
        commit: bool = True,
    ) -> None:
        timestamp = int(datetime.now(UTC).timestamp())
        self.execute(
            """INSERT INTO Polls
            (show, episode, poll_service, poll_id, timestamp)
            VALUES (?, ?, ?, ?, ?)""",
            (show.id, episode.number, site.id, poll_id, timestamp),
        )
        if commit:
            self.commit()

    @db_error
    def update_poll_score(self, poll: Poll, score: float, commit: bool = True) -> None:
        self.execute(
            "UPDATE Polls SET score = ? WHERE show = ? AND episode = ?",
            (score, poll.show_id, poll.episode),
        )
        if commit:
            self.commit()

    @db_error_default(None)
    def get_poll(self, show: Show, episode: Episode) -> Poll | None:
        q = self.execute(
            """SELECT
            show AS show_id, episode, poll_service AS service,
            poll_id AS id, timestamp AS date, score
            FROM Polls
            WHERE show = ? AND episode = ?""",
            (show.id, episode.number),
        )
        poll = q.fetchone()
        if not poll:
            return None
        return Poll(**poll)

    @db_error_default(cast(list[Poll], []))
    def get_polls_missing_score(self) -> list[Poll]:
        q = self.execute(
            """SELECT
            show AS show_id, episode, poll_service AS service,
            poll_id AS id, timestamp AS date, score
            FROM Polls
            WHERE score is NULL AND show IN (SELECT id FROM Shows where enabled = 1)"""
        )
        return [Poll(**poll) for poll in q.fetchall()]

    # Searching
    @db_error_default(cast(set[int], set()))
    def search_show_ids_by_names(self, *names: str, exact: bool = False) -> set[int]:
        shows: set[int] = set()
        for name in names:
            logger.debug("Searching shows by name: %s", name)
            if exact:
                q = self.execute(
                    "SELECT show, name FROM ShowNames WHERE name = ?", (name,)
                )
            else:
                q = self.execute(
                    "SELECT show, name FROM ShowNames WHERE name = ? COLLATE alphanum",
                    (name,),
                )
            matched = q.fetchall()
            for match in matched:
                logger.debug("  Found match: %s | %s", match["show"], match["name"])
                shows.add(match["show"])
        return shows

    def _make_stream_from_query(self, row: dict[str, Any]) -> Stream | None:
        show_id: int = row["show"]
        show = self.get_show(show_id)
        if not show:
            logger.debug("Could not get show %s from stream", show_id)
            return None
        return Stream(**(dict(row) | {"show": show}))

    def _make_show_from_query(self, row: dict[str, Any]) -> Show:
        show = Show(**row)
        show.aliases = self.get_aliases(show)
        return show


# Helper methods

## Conversions


def to_show_type(db_val: int) -> ShowType:
    try:
        return ShowType(db_val)
    except ValueError:
        return ShowType.UNKNOWN


def from_show_type(show_type: ShowType) -> int | None:
    if not show_type:
        return None
    return show_type.value


## Collations


def _collate_alphanum(str1: str, str2: str) -> int:
    str1 = _alphanum_convert(str1)
    str2 = _alphanum_convert(str2)

    if str1 == str2:
        return 0
    if str1 < str2:
        return -1
    return 1


_alphanum_regex = re.compile("[^a-zA-Z0-9]+")
_romanization_o = re.compile("\bwo\b")


def _alphanum_convert(s: str) -> str:
    # TODO: punctuation is sometimes important to distinguish between seasons (ex. K-On! and K-On!!)
    # 6/28/16: The purpose of this function is weak collation;
    # use of punctuation to distinguish between seasons
    # can be done later when handling multiple found shows.

    # Characters to words
    s = s.replace("&", "and")
    # Japanese romanization differences
    s = _romanization_o.sub("o", s)
    s = s.replace("uu", "u")
    s = s.replace("wo", "o")

    s = _alphanum_regex.sub("", s)
    s = s.lower()
    return unidecode(s)
