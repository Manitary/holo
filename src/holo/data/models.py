import copy
import enum
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import struct_time
from typing import Self

logger = logging.getLogger(__name__)


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
    name: str
    name_en: str = ""
    length: int = 0
    show_type: int = ShowType.UNKNOWN.value
    has_source: int | bool = False
    is_nsfw: int | bool = False
    enabled: int | bool = True
    delayed: int | bool = False
    _aliases: list[str] = field(default_factory=list)

    @property
    def aliases(self) -> list[str]:
        return self._aliases

    @aliases.setter
    def aliases(self, names: list[str]) -> None:
        self._aliases = names

    @property
    def type(self) -> str:
        return ShowType(self.show_type).name

    def __str__(self) -> str:
        return f"Show: {self.name} (id={self.id}, type={self.show_type}, len={self.length})"


@dataclass(init=False)
class Episode:
    def __init__(
        self,
        number: int,
        name: str = "",
        link: str = "",
        date: datetime | struct_time | None = None,
    ) -> None:
        self.number = number
        self.name = name  # Not stored in database
        self.link = link
        if isinstance(date, datetime):
            self.date = date
        elif date:
            self.date = datetime(*date[:6])
        else:
            self.date = None

    def __str__(self) -> str:
        return (
            f"Episode: {self.date} | Episode {self.number}, {self.name} ({self.link})"
        )

    @property
    def is_live(self) -> bool:
        if not self.date:
            logger.warning("Episode %s does not have a date assigned", self.number)
            return False
        return datetime.now(UTC).replace(tzinfo=None) >= self.date

    @property
    def is_live_local(self) -> bool:
        if not self.date:
            logger.warning("Episode %s does not have a date assigned", self.number)
            return False
        return datetime.now() >= self.date


@dataclass
class EpisodeScore:
    show_id: int
    episode: int
    site_id: int = 0
    score: float = 0


@dataclass(eq=False)
class Service(DbEqMixin):
    key: str = ""
    name: str = ""
    enabled: int = 1
    use_in_post: int = 1

    def __str__(self) -> str:
        return f"Service: {self.key} ({self.id})"


@dataclass(eq=False)
class Stream(DbEqMixin):
    """
    remote_offset: relative to a start episode of 1
            If a stream numbers new seasons after ones before, remote_offset should be positive.
            If a stream numbers starting before 1 (ex. 0), remote_offset should be negative.
    display_offset: relative to the internal numbering starting at 1
            If a show should be displayed with higher numbering (ex. continuing after a split cour),
            display_offset should be positive.
            If a show should be numbered lower than 1 (ex. 0), display_offset should be negative.
    """

    service: int
    show: Show
    show_id: int
    show_key: str
    name: str
    remote_offset: int = 0
    display_offset: int = 0
    active: int | bool = True

    def __str__(self) -> str:
        return (
            f"Stream: {self.show} ({self.show_key}@{self.service}), "
            f"{self.remote_offset} {self.display_offset}"
        )

    @classmethod
    def from_show(cls, show: Show) -> Self:
        return Stream(
            id=-show.id,
            service=-1,
            show=show,
            show_id=show.id,
            show_key=show.name,
            name=show.name,
        )

    def to_internal_episode(self, episode: Episode) -> Episode:
        e = copy.copy(episode)
        e.number -= self.remote_offset
        return e

    def to_display_episode(self, episode: Episode) -> Episode:
        e = copy.copy(episode)
        e.number += self.display_offset
        return e


@dataclass(eq=False)
class LinkSite(DbEqMixin):
    key: str
    name: str
    enabled: int | bool = True

    def __str__(self) -> str:
        return f"Link site: {self.key} {self.id} ({self.enabled})"


@dataclass
class Link:
    site: str
    show: int
    site_key: str

    def __str__(self) -> str:
        return f"Link: {self.site_key}@{self.site}, show={self.show}"


@dataclass(eq=False)
class PollSite(DbEqMixin):
    key: str

    def __str__(self) -> str:
        return f"Poll site: {self.key}"


@dataclass(init=False)
class Poll:
    def __init__(
        self,
        show_id: int,
        episode: int,
        service: int,
        id: str,
        date: datetime | str,
        score: float | None,
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
    show: int
    service: str
    service_name: str
    url: str

    def __str__(self) -> str:
        return f"LiteStream: {self.service}|{self.service_name}, show={self.show}, url={self.url}"


@dataclass
class UnprocessedShow:
    site_key: str = ""
    show_key: str = ""
    name: str = ""
    name_en: str = ""
    more_names: list[str] = field(default_factory=list)
    show_type: ShowType = ShowType.UNKNOWN
    episode_count: int = 0
    has_source: int | bool = False
    is_nsfw: int | bool = False


@dataclass
class UnprocessedStream:
    service_key: str = ""
    show_key: str = ""
    show_id: int = 0
    name: str = ""
    remote_offset: int = 0
    display_offset: int = 0
