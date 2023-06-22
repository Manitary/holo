import copy
import enum
from datetime import datetime
from time import struct_time
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


class DbEqMixin:
    def __eq__(self, other: Self) -> bool:
        return self.id == other.id

    def __ne__(self, other: Self) -> bool:
        return self.id != other.id

    def __hash__(self) -> int:
        return hash(self.id)


class Show(DbEqMixin):
    def __init__(
        self,
        id: int,
        name: str,
        name_en: str,
        length: int,
        show_type: int,
        has_source: int,
        is_nsfw: int,
        enabled: int,
        delayed: int,
    ) -> None:
        self.id = id
        self.name = name
        self.name_en = name_en
        self.length = length
        self.type = show_type
        self.has_source = has_source == 1
        self.is_nsfw = is_nsfw == 1
        self.enabled = enabled
        self.delayed = delayed

    @property
    def aliases(self) -> list[str]:
        return self._aliases if hasattr(self, "_aliases") else []

    @aliases.setter
    def aliases(self, names: list[str]) -> None:
        self._aliases = names

    def __str__(self) -> str:
        return f"Show: {self.name} (id={self.id}, type={self.type}, len={self.length})"


class Episode:
    def __init__(
        self,
        number: int,
        name: str | None = None,
        link: str | None = None,
        date: datetime | struct_time | None = None,
    ) -> None:
        self.number = number
        self.name = name  # Not stored in database
        self.link = link
        if isinstance(date, datetime):
            self.date = date
        elif date:
            self.date = datetime(*date[:6])

    def __str__(self) -> str:
        return (
            f"Episode: {self.date} | Episode {self.number}, {self.name} ({self.link})"
        )

    @property
    def is_live(self, local: bool = False) -> bool:
        now = datetime.now() if local else datetime.utcnow()
        return now >= self.date


class EpisodeScore:
    def __init__(
        self, show_id: int, episode: int, score: float, site_id: int | None = None
    ) -> None:
        self.show_id = show_id
        self.episode = episode
        self.site_id = site_id
        self.score = score


class Service(DbEqMixin):
    def __init__(
        self, id: int, key: str, name: str, enabled: int, use_in_post: int
    ) -> None:
        self.id = id
        self.key = key
        self.name = name
        self.enabled = enabled == 1
        self.use_in_post = use_in_post == 1

    def __str__(self) -> str:
        return f"Service: {self.key} ({self.id})"


class Stream(DbEqMixin):
    """
    remote_offset: relative to a start episode of 1
            If a stream numbers new seasons after ones before, remote_offset should be positive.
            If a stream numbers starting before 1 (ex. 0), remote_offset should be negative.
    display_offset: relative to the internal numbering starting at 1
            If a show should be displayed with higher numbering (ex. continuing after a split cour), display_offset should be positive.
            If a show should be numbered lower than 1 (ex. 0), display_offset should be negative.
    """

    def __init__(
        self,
        id: int,
        service: int,
        show: Show,
        show_id: int,
        show_key: str,
        name: str,
        remote_offset: int,
        display_offset: int,
        active: int,
    ) -> None:
        self.id = id
        self.service = service
        self.show = show
        self.show_id = show_id
        self.show_key = show_key
        self.name = name
        self.remote_offset = remote_offset
        self.display_offset = display_offset
        self.active = active

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
            remote_offset=0,
            display_offset=0,
            active=1,
        )

    def to_internal_episode(self, episode: Episode) -> Episode:
        e = copy.copy(episode)
        e.number -= self.remote_offset
        return e

    def to_display_episode(self, episode: Episode) -> Episode:
        e = copy.copy(episode)
        e.number += self.display_offset
        return e


class LinkSite(DbEqMixin):
    def __init__(self, id: int, key: str, name: str, enabled: int) -> None:
        self.id = id
        self.key = key
        self.name = name
        self.enabled = enabled == 1

    def __str__(self) -> str:
        return f"Link site: {self.key} {self.id} ({self.enabled})"


class Link:
    def __init__(self, site: int, show: int, site_key: str) -> None:
        self.site = site
        self.show = show
        self.site_key = site_key

    def __str__(self) -> str:
        return f"Link: {self.site_key}@{self.site}, show={self.show}"


class PollSite(DbEqMixin):
    def __init__(self, id: int, key: str) -> None:
        self.id = id
        self.key = key

    def __str__(self) -> str:
        return f"Poll site: {self.key}"


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


class LiteStream:
    def __init__(self, show: int, service: str, service_name: str, url: str) -> None:
        self.show = show
        self.service = service
        self.service_name = service_name
        self.url = url

    def __str__(self) -> str:
        return f"LiteStream: {self.service}|{self.service_name}, show={self.show}, url={self.url}"


class UnprocessedShow:
    def __init__(
        self,
        name: str,
        show_type: ShowType,
        episode_count: int,
        has_source: int,
        is_nsfw: bool = False,
        site_key: str | None = None,
        show_key: str | None = None,
        name_en: str | None = None,
        more_names: list[str] | None = None,
    ) -> None:
        self.site_key = site_key
        self.show_key = show_key
        self.name = name
        self.name_en = name_en
        self.more_names = more_names or []
        self.show_type = show_type
        self.episode_count = episode_count
        self.has_source = has_source
        self.is_nsfw = is_nsfw


class UnprocessedStream:
    def __init__(
        self,
        service_key: str,
        show_key: str,
        remote_offset: int,
        display_offset: int,
        show_id: str | None = None,
        name: str = "",
    ) -> None:
        self.service_key = service_key
        self.show_key = show_key
        self.show_id = show_id
        self.name = name
        self.remote_offset = remote_offset
        self.display_offset = display_offset
