from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache, wraps
from typing import Any, Callable, TypeVar

from unidecode import unidecode

from services import AbstractInfoHandler, AbstractPollHandler, AbstractServiceHandler

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

T = TypeVar("T")
T0 = TypeVar("T0")


def living_in(the_database: str | None) -> DatabaseDatabase | None:
	"""
	wow wow
	:param the_database:
	:return:
	"""
	if the_database is None:
		raise ValueError("No database assigned")
	try:
		db = sqlite3.connect(the_database)
		db.execute("PRAGMA foreign_keys=ON")
	except sqlite3.OperationalError:
		logger.error("Failed to open database, %s", the_database)
		return None
	return DatabaseDatabase(db)


# Database


def db_error(f: Callable[..., Any]) -> Callable[..., bool]:
	@wraps(wrapped=f)
	def protected(*args: Any, **kwargs: Any) -> bool:
		try:
			f(*args, **kwargs)
			return True
		except Exception:
			logger.exception("Database exception thrown")
			return False

	return protected


def db_error_default(
	default_value: T0,
) -> Callable[[Callable[..., T]], Callable[..., T | T0]]:
	value = default_value

	def decorate(f: Callable[..., T]) -> Callable[..., T | T0]:
		@wraps(wrapped=f)
		def protected(*args: Any, **kwargs: Any) -> T | T0:
			nonlocal value
			try:
				return f(*args, **kwargs)
			except Exception:
				logger.exception("Database exception thrown")
				return value

		return protected

	return decorate


class DatabaseDatabase:
	def __init__(self, db: sqlite3.Connection) -> None:
		self._db = db
		self.q = db.cursor()

		# Set up collations
		self._db.create_collation("alphanum", _collate_alphanum)

	def __getattr__(self, attr: str) -> Any:
		if attr in self.__dict__:
			return getattr(self, attr)
		return getattr(self._db, attr)

	def get_count(self) -> Any:
		return self.q.fetchone()[0]

	def save(self) -> None:
		self.commit()

	# Setup
	def setup_tables(self) -> None:
		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS ShowTypes (
			id	INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
			key	TEXT NOT NULL
		)"""
		)
		self.q.executemany(
			"INSERT OR IGNORE INTO ShowTypes (id, key) VALUES (?, ?)",
			[(t.value, t.name.lower()) for t in ShowType],
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS Shows (
			id			INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
			name		TEXT NOT NULL,
			name_en		TEXT,
			length		INTEGER,
			type		INTEGER NOT NULL,
			has_source	INTEGER NOT NULL DEFAULT 0,
			is_nsfw		INTEGER NOT NULL DEFAULT 0,
			enabled		INTEGER NOT NULL DEFAULT 1,
			delayed		INTEGER NOT NULL DEFAULT 0,
			FOREIGN KEY(type) REFERENCES ShowTypes(id)
		)"""
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS ShowNames (
			show		INTEGER NOT NULL,
			name		TEXT NOT NULL
		)"""
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS Aliases (
			show		INTEGER NOT NULL,
			alias		TEXT NOT NULL,
			FOREIGN KEY(show) REFERENCES Shows(id),
			UNIQUE(show, alias) ON CONFLICT IGNORE
		)"""
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS Services (
			id			INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
			key			TEXT NOT NULL UNIQUE,
			name		TEXT NOT NULL,
			enabled		INTEGER NOT NULL DEFAULT 0,
			use_in_post	INTEGER NOT NULL DEFAULT 1
		)"""
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS Streams (
			id				INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
			service			TEXT NOT NULL,
			show			INTEGER,
			show_id			TEXT,
			show_key		TEXT NOT NULL,
			name			TEXT,
			remote_offset	INTEGER NOT NULL DEFAULT 0,
			display_offset	INTEGER NOT NULL DEFAULT 0,
			active			INTEGER NOT NULL DEFAULT 1,
			FOREIGN KEY(service) REFERENCES Services(id),
			FOREIGN KEY(show) REFERENCES Shows(id)
		)"""
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS Episodes (
			show		INTEGER NOT NULL,
			episode		INTEGER NOT NULL,
			post_url	TEXT,
			UNIQUE(show, episode) ON CONFLICT REPLACE,
			FOREIGN KEY(show) REFERENCES Shows(id)
		)"""
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS LinkSites (
			id		INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
			key		TEXT NOT NULL UNIQUE,
			name	TEXT NOT NULL,
			enabled	INTEGER NOT NULL DEFAULT 1
		)"""
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS Links (
			show		INTEGER NOT NULL,
			site		INTEGER NOT NULL,
			site_key	TEXT NOT NULL,
			FOREIGN KEY(site) REFERENCES LinkSites(id)
			FOREIGN KEY(show) REFERENCES Shows(id)
		)"""
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS Scores (
			show		INTEGER NOT NULL,
			episode		INTEGER NOT NULL,
			site		INTEGER NOT NULL,
			score		REAL NOT NULL,
			FOREIGN KEY(show) REFERENCES Shows(id),
			FOREIGN KEY(site) REFERENCES LinkSites(id)
		)"""
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS LiteStreams (
			show			INTEGER NOT NULL,
			service			TEXT,
			service_name	TEXT NOT NULL,
			url				TEXT,
			UNIQUE(show, service) ON CONFLICT REPLACE,
			FOREIGN KEY(show) REFERENCES Shows(id)
		)"""
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS PollSites (
			id		INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
			key		TEXT NOT NULL UNIQUE
		)"""
		)

		self.q.execute(
			"""CREATE TABLE IF NOT EXISTS Polls (
			show			INTEGER NOT NULL,
			episode			INTEGER NOT NULL,
			poll_service	INTEGER NOT NULL,
			poll_id			TEXT NOT NULL,
			timestamp		INTEGER NOT NULL,
			score			REAL,
			FOREIGN KEY(show) REFERENCES Shows(id),
			FOREIGN KEY(poll_service) REFERENCES PollSites(id),
			UNIQUE(show, episode) ON CONFLICT REPLACE
		)"""
		)

		self.commit()

	def register_services(self, services: dict[str, AbstractServiceHandler]) -> None:
		self.q.execute("UPDATE Services SET enabled = 0")
		for service_key in services:
			service = services[service_key]
			self.q.execute(
				"INSERT OR IGNORE INTO Services (key, name) VALUES (?, '')",
				(service.key,),
			)
			self.q.execute(
				"UPDATE Services SET name = ?, enabled = 1 WHERE key = ?",
				(service.name, service.key),
			)
		self.commit()

	def register_link_sites(self, sites: dict[str, AbstractInfoHandler]) -> None:
		self.q.execute("UPDATE LinkSites SET enabled = 0")
		for site_key in sites:
			site = sites[site_key]
			self.q.execute(
				"INSERT OR IGNORE INTO LinkSites (key, name) VALUES (?, '')",
				(site.key,),
			)
			self.q.execute(
				"UPDATE LinkSites SET name = ?, enabled = 1 WHERE key = ?",
				(site.name, site.key),
			)
		self.commit()

	def register_poll_sites(self, polls: dict[str, AbstractPollHandler]) -> None:
		for poll_key in polls:
			poll = polls[poll_key]
			self.q.execute(
				"INSERT OR IGNORE INTO PollSites (key) VALUES (?)", (poll.key,)
			)
		self.commit()

	# Services
	@db_error_default(None)
	@lru_cache(10)
	def get_service(
		self, id: int | None = None, key: str | None = None
	) -> Service | None:
		# ! get_service with id is never used
		if id is not None:
			self.q.execute(
				"SELECT id, key, name, enabled, use_in_post FROM Services WHERE id = ?",
				(id,),
			)
		elif key is not None:
			self.q.execute(
				"SELECT id, key, name, enabled, use_in_post FROM Services WHERE key = ?",
				(key,),
			)
		else:
			logger.error("ID or key required to get service")
			return None
		service = self.q.fetchone()
		return Service(*service)

	empty_list_service: list[Service] = []

	@db_error_default(empty_list_service)
	def get_services(self, enabled: bool = True) -> list[Service]:
		services = [
			Service(*service)
			for service in self.q.execute(
				"SELECT id, key, name, enabled, use_in_post FROM Services WHERE enabled = ?",
				(1 if enabled else 0,),
			).fetchall()
		]
		return services

	@db_error_default(None)
	def get_stream(
		self, id: int | None = None, service_tuple: tuple[Service, str] | None = None
	) -> Stream | None:
		# ! get_stream with id is never used
		if id is not None:
			logger.debug("Getting stream for id %s", id)

			self.q.execute(
				"""SELECT
				id, service, show, show_id, show_key, name, remote_offset, display_offset, active 
				FROM Streams WHERE id = ?""",
				(id,),
			)
			stream = self.q.fetchone()
			if not stream:
				logger.error("Stream %s not found", id)
				return None
			stream = Stream(*stream)
		elif service_tuple is not None:
			service, show_key = service_tuple
			logger.debug("Getting stream for %s/%s", service, show_key)
			self.q.execute(
				"""SELECT
				id, service, show, show_id, show_key, name, remote_offset, display_offset, active 
				FROM Streams WHERE service = ? AND show_key = ?""",
				(service.id, show_key),
			)
			stream = self.q.fetchone()
			if not stream:
				logger.error("Stream %s not found", id)
				return None
			stream = Stream(*stream)
		else:
			logger.error("Nothing provided to get stream")
			return None

		stream.show = self.get_show(id=stream.show)  # convert show id to show model
		return stream

	empty_list_stream: list[Stream] = []

	@db_error_default(empty_list_stream)
	def get_streams(
		self,
		service: Service | None = None,
		show: Show | None = None,
		active: bool = True,
		unmatched: bool = False,
		missing_name: bool = False,
	) -> list[Stream]:
		# Not the best combination of options, but it's only the usage needed
		# ! Only 'service' is ever set. What is the rest for?
		if service and active:
			logger.debug("Getting all active streams for service %s", service.key)
			service = self.get_service(key=service.key)
			self.q.execute(
				"""SELECT
				id, service, show, show_id, show_key, name, remote_offset, display_offset, active
				FROM Streams
				WHERE service = ? AND active = 1 AND
				(SELECT enabled FROM Shows WHERE id = show) = 1""",
				(service.id,),
			)
		elif service and not active:
			logger.debug("Getting all inactive streams for service %s", service.key)
			service = self.get_service(key=service.key)
			self.q.execute(
				"""SELECT
				id, service, show, show_id, show_key, name, remote_offset, display_offset, active
				FROM Streams
				WHERE service = ? AND active = 0""",
				(service.id,),
			)
		elif show and active:
			logger.debug("Getting all streams for show %s", show.id)
			self.q.execute(
				"""SELECT
				id, service, show, show_id, show_key, name, remote_offset, display_offset, active
				FROM Streams
				WHERE show = ? AND active = 1 AND
				(SELECT enabled FROM Shows WHERE id = show) = 1""",
				(show.id,),
			)
		elif show and not active:
			logger.debug("Getting all streams for show %s", show.id)
			self.q.execute(
				"""SELECT
				id, service, show, show_id, show_key, name, remote_offset, display_offset, active
				FROM Streams
				WHERE show = ? AND active = 0""",
				(show.id,),
			)
		elif unmatched:
			logger.debug("Getting unmatched streams")
			self.q.execute(
				"""SELECT
				id, service, show, show_id, show_key, name, remote_offset, display_offset, active
				FROM Streams
				WHERE show IS NULL"""
			)
		elif missing_name and active:
			self.q.execute(
				"""SELECT
				id, service, show, show_id, show_key, name, remote_offset, display_offset, active
				FROM Streams
				WHERE (name IS NULL OR name = '') AND active = 1 AND
				(SELECT enabled FROM Shows WHERE id = show) = 1"""
			)
		elif missing_name and not active:
			self.q.execute(
				"""SELECT
				id, service, show, show_id, show_key, name, remote_offset, display_offset, active
				FROM Streams
				WHERE (name IS NULL OR name = '') AND active = 0"""
			)
		else:
			logger.error("A service or show must be provided to get streams")
			return []

		streams = self.q.fetchall()
		streams = [Stream(*stream) for stream in streams]
		for stream in streams:
			stream.show = self.get_show(id=stream.show)  # convert show id to show model
		return streams

	@db_error_default(False)
	def has_stream(self, service_key: str, show_key: str) -> bool:
		service = self.get_service(key=service_key)
		if not service:
			return False
		self.q.execute(
			"SELECT count(*) FROM Streams WHERE service = ? AND show_key = ?",
			(service.id, show_key),
		)
		return self.get_count() > 0

	@db_error
	def add_stream(
		self, raw_stream: UnprocessedStream, show_id: int | None, commit: bool = True
	) -> None:
		logger.debug("Inserting stream: %s", raw_stream)

		service = self.get_service(key=raw_stream.service_key)
		if not service:
			logger.warning(
				"Service not found. Cannot add stream for show %s. Raw stream data: %s",
				show_id,
				raw_stream,
			)
		self.q.execute(
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
		show: Show | None = None,
		active: bool | int | None = None,
		name: str | None = None,
		show_id: int | None = None,
		show_key: str | None = None,
		remote_offset: int | None = None,
		commit: bool = True,
	) -> None:
		logger.debug("Updating stream: id=%s", stream.id)
		if show is not None:
			self.q.execute(
				"UPDATE Streams SET show = ? WHERE id = ?", (show, stream.id)
			)
		if active is not None:
			self.q.execute(
				"UPDATE Streams SET active = ? WHERE id = ?", (active, stream.id)
			)
		if name is not None:
			self.q.execute(
				"UPDATE Streams SET name = ? WHERE id = ?", (name, stream.id)
			)
		if show_id is not None:
			self.q.execute(
				"UPDATE Streams SET show_id = ? WHERE id = ?", (show_id, stream.id)
			)
		if show_key is not None:
			self.q.execute(
				"UPDATE Streams SET show_key = ? WHERE id = ?", (show_key, stream.id)
			)
		if remote_offset is not None:
			self.q.execute(
				"UPDATE Streams SET remote_offset = ? WHERE id = ?",
				(remote_offset, stream.id),
			)

		if commit:
			self.commit()

	# Infos
	empty_list_lite_stream: list[LiteStream] = []

	@db_error_default(empty_list_lite_stream)
	def get_lite_streams(
		self,
		service: Service | None = None,
		show: Show | None = None,
		missing_link: bool = False,
	) -> list[LiteStream]:
		if service is not None:
			logger.debug("Getting all lite streams for service key %s", service)
			self.q.execute(
				"""SELECT show, service, service_name, url FROM LiteStreams
				WHERE service = ?""",
				(service,),
			)
		elif show is not None:
			logger.debug("Getting all lite streams for show %s", show)
			self.q.execute(
				"""SELECT show, service, service_name, url FROM LiteStreams
				WHERE show = ?""",
				(show.id,),
			)
		elif missing_link:
			logger.debug("Getting lite streams without link")
			self.q.execute(
				"""SELECT show, service, service_name, url FROM LiteStreams
				WHERE url IS NULL"""
			)
		else:
			logger.error("A service or show must be provided to get lite streams")
			return []

		lite_streams = [LiteStream(*lite_stream) for lite_stream in self.q.fetchall()]
		return lite_streams

	@db_error
	def add_lite_stream(
		self, show: Show, service: Service, service_name: str, url: str
	) -> None:
		logger.debug("Inserting lite stream %s (%s) for show %s", service, url, show)
		self.q.execute(
			"INSERT INTO LiteStreams (show, service, service_name, url) values (?, ?, ?, ?)",
			(show, service, service_name, url),
		)
		self.commit()

	# Links
	@db_error_default(None)
	def get_link_site(
		self, id: str | None = None, key: str | None = None
	) -> LinkSite | None:
		if id is not None:
			self.q.execute(
				"SELECT id, key, name, enabled FROM LinkSites WHERE id = ?", (id,)
			)
		elif key is not None:
			self.q.execute(
				"SELECT id, key, name, enabled FROM LinkSites WHERE key = ?", (key,)
			)
		else:
			logger.error("ID or key required to get link site")
			return None
		site = self.q.fetchone()
		if site is None:
			return None
		return LinkSite(*site)

	empty_list_link_site: list[LinkSite] = []

	@db_error_default(empty_list_link_site)
	def get_link_sites(self, enabled: bool = True) -> list[LinkSite]:
		sites = [
			LinkSite(*link)
			for link in self.q.execute(
				"SELECT id, key, name, enabled FROM LinkSites WHERE enabled = ?",
				(1 if enabled else 0,),
			).fetchall()
		]
		return sites

	empty_list_link: list[Link] = []

	@db_error_default(empty_list_link)
	def get_links(self, show: Show | None = None) -> list[Link]:
		if not show:
			logger.error("A show must be provided to get links")
			return []

		logger.debug("Getting all links for show %s", show.id)
		# Get all streams with show ID
		self.q.execute(
			"SELECT site, show, site_key FROM Links WHERE show = ?", (show.id,)
		)
		links = [Link(*link) for link in self.q.fetchall()]
		return links

	@db_error_default(None)
	def get_link(self, show: Show, link_site: LinkSite) -> Link | None:
		logger.debug("Getting link for show %s and site %s", show.id, link_site.key)
		self.q.execute(
			"SELECT site, show, site_key FROM Links WHERE show = ? AND site = ?",
			(show.id, link_site.id),
		)
		link = self.q.fetchone()
		if not link:
			return None
		return Link(*link)

	@db_error_default(False)
	def has_link(self, site_key: str, key: str, show: int | None = None) -> bool:
		site = self.get_link_site(key=site_key)
		if not site:
			logger.warning("Cannot find site with key %s", site_key)
			return False
		if show:
			self.q.execute(
				"SELECT count(*) FROM Links WHERE site = ? AND site_key = ? AND show = ?",
				(site.id, key, show),
			)
		else:
			self.q.execute(
				"SELECT count(*) FROM Links WHERE site = ? AND site_key = ?",
				(site.id, key),
			)
		return self.get_count() > 0

	@db_error
	def add_link(
		self, raw_show: UnprocessedShow, show_id: int, commit: bool = True
	) -> None:
		logger.debug("Inserting link: %s/%s", show_id, raw_show)

		site = self.get_link_site(key=raw_show.site_key)
		if site is None:
			logger.error('  Invalid site "%s"', raw_show.site_key)
			return
		site_key = raw_show.show_key

		self.q.execute(
			"INSERT INTO Links (show, site, site_key) VALUES (?, ?, ?)",
			(show_id, site.id, site_key),
		)
		if commit:
			self.commit()

	# Shows
	empty_list_show: list[Show] = []

	@db_error_default(empty_list_show)
	def get_shows(
		self,
		missing_length: bool = False,
		missing_stream: bool = False,
		enabled: bool = True,
		delayed: bool = False,
	) -> list[Show]:
		if missing_length:
			self.q.execute(
				"""SELECT id, name, name_en, length, type, has_source, is_nsfw, enabled, delayed
				FROM Shows
				WHERE (length IS NULL OR length = '' OR length = 0) AND enabled = ?""",
				(enabled,),
			)
		elif missing_stream:
			self.q.execute(
				"""SELECT
				id, name, name_en, length, type, has_source, is_nsfw, enabled, delayed
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
		elif delayed:
			self.q.execute(
				"""SELECT id, name, name_en, length, type, has_source, is_nsfw, enabled, delayed
				FROM Shows
				WHERE delayed = 1 AND enabled = ?""",
				(enabled,),
			)
		else:
			self.q.execute(
				"""SELECT id, name, name_en, length, type, has_source, is_nsfw, enabled, delayed
				FROM Shows
				WHERE enabled = ?""",
				(enabled,),
			)
		shows: list[Show] = []
		for show in self.q.fetchall():
			show = Show(*show)
			show.aliases = self.get_aliases(show)
			shows.append(show)
		return shows

	@db_error_default(None)
	def get_show(
		self, id: int | None = None, stream: Stream | None = None
	) -> Show | None:
		# logger.debug("Getting show from database")

		# Get show ID
		if stream and not id:
			id = stream.show.id

		# Get show
		if id is None:
			logger.error("Show ID not provided to get_show")
			return None

		self.q.execute(
			"""SELECT id, name, name_en, length, type, has_source, is_nsfw, enabled, delayed
			FROM Shows
			WHERE id = ?""",
			(id,),
		)
		show = self.q.fetchone()
		if show is None:
			return None
		show = Show(*show)
		show.aliases = self.get_aliases(show)
		return show

	@db_error_default(None)
	def get_show_by_name(self, name: str) -> Show | None:
		# logger.debug("Getting show from database")

		self.q.execute(
			"""SELECT id, name, name_en, length, type, has_source, is_nsfw, enabled, delayed
			FROM Shows
			WHERE name = ?""",
			(name,),
		)
		show = self.q.fetchone()
		if show is None:
			return None
		show = Show(*show)
		show.aliases = self.get_aliases(show)
		return show

	empty_list_string: list[str] = []

	@db_error_default(empty_list_string)
	def get_aliases(self, show: Show) -> list[str]:
		self.q.execute("SELECT alias FROM Aliases where show = ?", (show.id,))
		return [s for s, in self.q.fetchall()]

	@db_error_default(None)
	def add_show(self, raw_show: UnprocessedShow, commit: bool = True) -> int | None:
		logger.debug("Inserting show: %s", raw_show)

		name = raw_show.name
		name_en = raw_show.name_en
		length = raw_show.episode_count
		show_type = from_show_type(raw_show.show_type)
		has_source = raw_show.has_source
		is_nsfw = raw_show.is_nsfw
		self.q.execute(
			"""INSERT INTO Shows
			(name, name_en, length, type, has_source, is_nsfw)
			VALUES (?, ?, ?, ?, ?, ?)""",
			(name, name_en, length, show_type, has_source, is_nsfw),
		)
		show_id = self.q.lastrowid
		self.add_show_names(
			raw_show.name, *raw_show.more_names, id=show_id, commit=commit
		)

		if commit:
			self.commit()

		return show_id

	@db_error
	def add_alias(self, show_id: int, alias: str, commit: bool = True) -> None:
		self.q.execute(
			"INSERT INTO Aliases (show, alias) VALUES (?, ?)", (show_id, alias)
		)
		if commit:
			self.commit()

	@db_error_default(None)
	def update_show(
		self, show_id: str, raw_show: UnprocessedShow, commit: bool = True
	) -> None:
		logger.debug("Updating show: %s", raw_show)

		# name = raw_show.name
		name_en = raw_show.name_en
		length = raw_show.episode_count
		show_type = from_show_type(raw_show.show_type)
		has_source = raw_show.has_source
		is_nsfw = raw_show.is_nsfw

		if name_en:
			self.q.execute(
				"UPDATE Shows SET name_en = ? WHERE id = ?", (name_en, show_id)
			)
		if length != 0:
			self.q.execute(
				"UPDATE Shows SET length = ? WHERE id = ?", (length, show_id)
			)
		self.q.execute(
			"UPDATE Shows SET type = ?, has_source = ?, is_nsfw = ? WHERE id = ?",
			(show_type, has_source, is_nsfw, show_id),
		)

		if commit:
			self.commit()

	@db_error
	def add_show_names(
		self, *names: str, id: int | None = None, commit: bool = True
	) -> None:
		self.q.executemany(
			"INSERT INTO ShowNames (show, name) VALUES (?, ?)",
			[(id, name) for name in names],
		)
		if commit:
			self.commit()

	@db_error
	def set_show_episode_count(self, show: Show, length: int) -> None:
		logger.debug(
			"Updating show episode count in database: %s, %s", show.name, length
		)
		self.q.execute("UPDATE Shows SET length = ? WHERE id = ?", (length, show.id))
		self.commit()

	@db_error
	def set_show_delayed(self, show: Show, delayed: bool = True) -> None:
		logger.debug("Marking show %s as delayed: %s", show.name, delayed)
		self.q.execute("UPDATE Shows SET delayed = ? WHERE id = ?", (delayed, show.id))
		self.commit()

	@db_error
	def set_show_enabled(
		self, show: Show, enabled: bool = True, commit: bool = True
	) -> None:
		logger.debug(
			"Marking show %s as %s", show.name, "enabled" if enabled else "disabled"
		)
		self.q.execute("UPDATE Shows SET enabled = ? WHERE id = ?", (enabled, show.id))
		if commit:
			self.commit()

	# Episodes
	@db_error_default(True)
	def stream_has_episode(self, stream: Stream, episode_num: int) -> bool:
		self.q.execute(
			"SELECT count(*) FROM Episodes WHERE show = ? AND episode = ?",
			(stream.show, episode_num),
		)
		num_found = self.get_count()
		logger.debug(
			"Found %s entries matching show %s, episode %s",
			num_found,
			stream.show,
			episode_num,
		)
		return num_found > 0

	@db_error_default(None)
	def get_latest_episode(self, show: Show) -> Episode | None:
		self.q.execute(
			"SELECT episode, post_url FROM Episodes WHERE show = ? ORDER BY episode DESC LIMIT 1",
			(show.id,),
		)
		data = self.q.fetchone()
		if not data:
			return None
		return Episode(number=data[0], name="", link=data[1], date=None)

	@db_error
	def add_episode(self, show: Show, episode_num: int, post_url: str) -> None:
		logger.debug(
			"Inserting episode %s for show %s (%s)", episode_num, show.id, post_url
		)
		self.q.execute(
			"INSERT INTO Episodes (show, episode, post_url) VALUES (?, ?, ?)",
			(show.id, episode_num, post_url),
		)
		self.commit()

	empty_list_episode: list[Episode] = []

	@db_error_default(empty_list_episode)
	def get_episodes(self, show: Show, ensure_sorted: bool = True) -> list[Episode]:
		self.q.execute(
			"SELECT episode, post_url FROM Episodes WHERE show = ?", (show.id,)
		)
		episodes = [
			Episode(number=data[0], name="", link=data[1], date=None)
			for data in self.q.fetchall()
		]

		if ensure_sorted:
			episodes = sorted(episodes, key=lambda e: e.number)
		return episodes

	empty_list_episode_score: list[EpisodeScore] = []
	# Scores
	@db_error_default(empty_list_episode_score)
	def get_show_scores(self, show: Show) -> list[EpisodeScore]:
		self.q.execute(
			"SELECT episode, site, score FROM Scores WHERE show=?", (show.id,)
		)
		return [EpisodeScore(show.id, *s) for s in self.q.fetchall()]

	@db_error_default(empty_list_episode_score)
	def get_episode_scores(self, show: Show, episode: Episode) -> list[EpisodeScore]:
		self.q.execute(
			"SELECT site, score FROM Scores WHERE show=? AND episode=?",
			(show.id, episode.number),
		)
		return [EpisodeScore(show.id, episode.number, *s) for s in self.q.fetchall()]

	@db_error_default(None)
	def get_episode_score_avg(
		self, show: Show, episode: Episode
	) -> EpisodeScore | None:
		logger.debug("Calculating avg score for %s (%s)", show.name, show.id)
		self.q.execute(
			"SELECT score FROM Scores WHERE show=? AND episode=?",
			(show.id, episode.number),
		)
		scores = [s[0] for s in self.q.fetchall()]
		if scores:
			score = sum(scores) / len(scores)
			logger.debug("  Score: %s (from %s scores)", score, len(scores))
			return EpisodeScore(
				show_id=show.id, episode=episode.number, site_id=None, score=score
			)
		return None

	@db_error
	def add_episode_score(
		self,
		show: Show,
		episode: Episode,
		site: LinkSite,
		score: float,
		commit: bool = True,
	) -> None:
		self.q.execute(
			"INSERT INTO Scores (show, episode, site, score) VALUES (?, ?, ?, ?)",
			(show.id, episode.number, site.id, score),
		)
		if commit:
			self.commit()

	# Polls

	@db_error_default(None)
	def get_poll_site(
		self, id: str | None = None, key: str | None = None
	) -> PollSite | None:
		if id is not None:
			self.q.execute("SELECT id, key FROM PollSites WHERE id = ?", (id,))
		elif key is not None:
			self.q.execute("SELECT id, key FROM PollSites WHERE key = ?", (key,))
		else:
			logger.error("ID or key required to get poll site")
			return None
		site = self.q.fetchone()
		if site is None:
			return None
		return PollSite(*site)

	@db_error
	def add_poll(
		self,
		show: Show,
		episode: Episode,
		site: PollSite,
		poll_id: str,
		commit: bool = True,
	) -> None:
		timestamp = int(datetime.now(timezone.utc).timestamp())
		self.q.execute(
			"""INSERT INTO Polls
			(show, episode, poll_service, poll_id, timestamp)
			VALUES (?, ?, ?, ?, ?)""",
			(show.id, episode.number, site.id, poll_id, timestamp),
		)
		if commit:
			self.commit()

	@db_error
	def update_poll_score(self, poll: Poll, score: float, commit: bool = True) -> None:
		self.q.execute(
			"UPDATE Polls SET score = ? WHERE show = ? AND episode = ?",
			(score, poll.show_id, poll.episode),
		)
		if commit:
			self.commit()

	@db_error_default(None)
	def get_poll(self, show: Show, episode: Episode) -> Poll | None:
		self.q.execute(
			"""SELECT show, episode, poll_service, poll_id, timestamp, score
			FROM Polls
			WHERE show = ? AND episode = ?""",
			(show.id, episode.number),
		)
		poll = self.q.fetchone()
		if poll is None:
			return None
		return Poll(*poll)

	empty_list_poll: list[Poll] = []

	@db_error_default(empty_list_poll)
	def get_polls(
		self, show: Show | None = None, missing_score: bool = False
	) -> list[Poll]:
		if show is not None:
			self.q.execute(
				"""SELECT show, episode, poll_service, poll_id, timestamp, score
				FROM Polls WHERE show = ?""",
				(show.id,),
			)
		elif missing_score:
			self.q.execute(
				"""SELECT show, episode, poll_service, poll_id, timestamp, score
				FROM Polls
				WHERE score is NULL
				AND show IN (SELECT id FROM Shows where enabled = 1)"""
			)
		else:
			logger.error("Need to select a show to get polls")
			return []
		polls = [Poll(*poll) for poll in self.q.fetchall()]
		return polls

	# Searching
	empty_set_int: set[int] = set()

	@db_error_default(empty_set_int)
	def search_show_ids_by_names(self, *names: str, exact: bool = False) -> set[int]:
		shows: set[int] = set()
		for name in names:
			logger.debug("Searching shows by name: %s", name)
			if exact:
				self.q.execute(
					"SELECT show, name FROM ShowNames WHERE name = ?", (name,)
				)
			else:
				self.q.execute(
					"SELECT show, name FROM ShowNames WHERE name = ? COLLATE alphanum",
					(name,),
				)
			matched = self.q.fetchall()
			for match in matched:
				logger.debug("  Found match: %s | %s", match[0], match[1])
				shows.add(match[0])
		return shows


# Helper methods

## Conversions


def to_show_type(db_val: str | int) -> ShowType:
	try:
		return ShowType(db_val)
	except ValueError:
		return ShowType.UNKNOWN


def from_show_type(show_type: ShowType | None) -> int | None:
	# ? Should not be needed anymore using EnumInt
	if show_type is None:
		return None
	return show_type.value


## Collations
def _collate_alphanum(str1: str, str2: str) -> int:
	str1 = _alphanum_convert(str1)
	str2 = _alphanum_convert(str2)

	if str1 == str2:
		return 0
	elif str1 < str2:
		return -1
	else:
		return 1


_alphanum_regex = re.compile("[^a-zA-Z0-9]+")
_romanization_o = re.compile("\bwo\b")


def _alphanum_convert(s: str) -> str:
	# TODO: punctuation is important for some shows to distinguish between seasons (ex. K-On! and K-On!!)
	# 6/28/16: The purpose of this function is weak collation;
	# use of punctuation to distinguish between seasons can be done later
	# when handling multiple found shows.

	# Characters to words
	s = s.replace("&", "and")
	# Japanese romanization differences
	s = _romanization_o.sub("o", s)
	s = s.replace("uu", "u")
	s = s.replace("wo", "o")

	s = _alphanum_regex.sub("", s)
	s = s.lower()
	return unidecode(s)
