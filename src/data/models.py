from datetime import datetime
from dataclasses import dataclass, field
import enum
import copy
from typing import Self


class ShowType(enum.IntEnum):
	UNKNOWN = 0
	TV = 1
	MOVIE = 2
	OVA = 3


def str_to_showtype(string: str) -> ShowType:
	try:
		return ShowType[string.strip().upper()]
	except KeyError:
		return ShowType.UNKNOWN


@dataclass
class DbEqMixin:
	id: int

	def __eq__(self, other: Self) -> bool:
		return self.id == other.id

	def __ne__(self, other: Self) -> bool:
		return self.id != other.id

	def __hash__(self) -> int:
		return hash(self.id)


@dataclass(eq=False)
class Show(DbEqMixin):
	# Note: arguments are order-sensitive
	name: str
	name_en: str
	length: int
	type: int
	has_source: int
	is_nsfw: int
	enabled: int
	delayed: int
	_aliases: list[str] = field(default_factory=list)

	@property
	def aliases(self) -> list[str]:
		return self._aliases

	@aliases.setter
	def aliases(self, names: list[str]) -> None:
		self._aliases = names

	def __str__(self) -> str:
		return f"Show: {self.name} (id={self.id}, type={self.type}, len={self.length})"


@dataclass
class Episode:
	def __init__(
		self, number: int, name: str, link: str, date: datetime | list[int]
	) -> None:
		# Note: arguments are order-sensitive
		self.number = number
		self.name = name  # Not stored in database
		self.link = link
		if isinstance(date, datetime):
			self.date = date
		elif date:
			self.date = datetime(*date[:6])  # type: ignore

	def __str__(self) -> str:
		return (
			f"Episode: {self.date} | Episode {self.number}, {self.name} ({self.link})"
		)

	@property
	def is_live(self, local: bool = False) -> bool:
		now = datetime.now() if local else datetime.utcnow()
		return now >= self.date


@dataclass
class EpisodeScore:
	show_id: int
	episode: int
	site_id: int
	score: float


@dataclass(eq=False)
class Service(DbEqMixin):
	# Note: arguments are order-sensitive
	key: str
	name: str
	enabled: int
	use_in_post: int

	def __str__(self) -> str:
		return f"Service: {self.key} ({self.id})"


@dataclass(eq=False)
class Stream(DbEqMixin):
	"""
	remote_offset: relative to a start episode of 1
		If a stream numbers new seasons after ones before, remote_offset should be positive.
		If a stream numbers starting before 1 (ex. 0), remote_offset should be negative.
	display_offset: relative to the internal numbering starting at 1
		If a show should be displayed with higher numbering (ex. continuing after a split cour), display_offset should be positive.
		If a show should be numbered lower than 1 (ex. 0), display_offset should be negative.
	"""

	# Note: arguments are order-sensitive
	service: int
	show: int
	show_id: str | None
	show_key: str
	name: str
	remote_offset: int = 0
	display_offset: int = 0
	active: int = 1

	def __str__(self) -> str:
		return (
			f"Stream: {self.show} ({self.show_key}@{self.service}), "
			f"{self.remote_offset} {self.display_offset}"
		)

	@classmethod
	def from_show(cls, show: Show) -> Self:
		return Stream(-show.id, -1, show.id, None, show.name, show.name)

	def to_internal_episode(self, episode: Episode) -> Episode:
		# ? Seems unused? Why a shallow copy instead of altering directly?
		e = copy.copy(episode)
		e.number -= self.remote_offset
		return e

	def to_display_episode(self, episode: Episode) -> Episode:
		# ? Seems unused? Why a shallow copy instead of altering directly?
		e = copy.copy(episode)
		e.number += self.display_offset
		return e


@dataclass(eq=False)
class LinkSite(DbEqMixin):
	# Note: arguments are order-sensitive
	key: str
	name: str
	enabled: int

	def __str__(self) -> str:
		return f"Link site: {self.key} ({self.id})"


@dataclass
class Link:
	# Note: arguments are order-sensitive
	site: str
	show: str
	site_key: str

	def __str__(self) -> str:
		return f"Link: {self.site_key}@{self.site}, show={self.show}"


@dataclass(eq=False)
class PollSite(DbEqMixin):
	key: str

	def __str__(self) -> str:
		return f"Poll site: {self.key}"


class Poll:
	def __init__(
		self,
		show_id: int,
		episode: int,
		service: int,
		id: str,
		date: datetime | str | int,
		score: float | None = None,
	) -> None:
		self.show_id = show_id
		self.episode = episode
		self.service_id = service
		self.id = id
		if isinstance(date, datetime):
			self.date = date
		else:
			self.date = datetime.fromtimestamp(int(date))
		self.score = score

	@property
	def has_score(self) -> bool:
		return self.score is not None

	def __str__(self) -> str:
		return f"Poll {self.show_id}/{self.episode} (Score {self.score})"


@dataclass
class LiteStream:
	# Note: arguments are order-sensitive
	show: int
	service: str
	service_name: str
	url: str

	def __str__(self) -> str:
		return f"LiteStream: {self.service}|{self.service_name}, show={self.show}, url={self.url}"


@dataclass
class UnprocessedShow:
	site_key: str
	show_key: str
	name: str
	name_en: str
	more_names: list[str]
	show_type: int
	episode_count: int
	has_source: int
	is_nsfw: int


@dataclass
class UnprocessedStream:
	service_key: str
	show_key: str
	show_id: int
	name: str
	remote_offset: int
	display_offset: int
