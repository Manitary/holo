import logging
import re
from datetime import datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup, Tag

from ...data.models import Episode, Stream, UnprocessedStream
from .. import AbstractServiceHandler

logger = logging.getLogger(__name__)


class ServiceHandler(AbstractServiceHandler):
    _show_url = "https://www.hidive.com/tv/{id}"
    _show_re = re.compile(r"hidive.com/tv/([\w-]+(?:/season-\d+)?)", re.I)
    _date_re = re.compile(r"Premiere: (\d+)/(\d+)/(\d+)")

    def __init__(self) -> None:
        super().__init__(key="hidive", name="HIDIVE", is_generic=False)

    # Episode finding

    def get_all_episodes(self, stream: Stream, **kwargs: Any) -> list[Episode]:
        logger.info("Getting live episodes for HiDive/%s", stream.show_key)

        episode_datas = self._get_feed_episodes(stream.show_key, **kwargs)

        # HIDIVE does not include episode date in the show's page
        # Pre-process the data to obtain all the other information
        # Sort the episodes by descending number
        # Stop at the first invalid episode
        # (Assumption: all new episodes have increasing numbers)
        # This is to reduce the number of requests to make
        episodes_candidates = sorted(
            list(filter(None, map(_preprocess_episode, episode_datas))),
            key=lambda e: e.number,
            reverse=True,
        )

        episodes: list[Episode] = []
        for episode in episodes_candidates:
            try:
                if episode := self._is_valid_episode(
                    episode=episode, show_key=stream.show_key, **kwargs
                ):
                    episodes.append(episode)
                else:
                    break
            except Exception:
                logger.exception(
                    "Problem digesting episode for HiDive/%s", stream.show_key
                )
        logger.debug("  %d episodes found, %d valid", len(episode_datas), len(episodes))
        return episodes

    def _get_feed_episodes(self, show_key: str, **kwargs: Any) -> list[Tag]:
        logger.info("Getting episodes for HiDive/%s", show_key)

        url = self._get_feed_url(show_key)

        response: BeautifulSoup | None = self.request_html(url=url, **kwargs)
        if not response:
            logger.error("Cannot get show page for HiDive/%s", show_key)
            return []

        sections = response.find_all("div", {"data-section": "episodes"})
        return sections

    @classmethod
    def _get_feed_url(cls, show_key: str) -> str:
        if show_key:
            return cls._show_url.format(id=show_key)
        return ""

    # Remove info getting

    def get_stream_info(self, stream: Stream, **kwargs: Any) -> Stream | None:
        logger.info("Getting stream info for HiDive/%s", stream.show_key)

        url = self._get_feed_url(stream.show_key)
        if not url:
            logger.error("Cannot get url from show key")
            return None
        response: BeautifulSoup | None = self.request_html(url, **kwargs)
        if not response:
            logger.error("Cannot get feed")
            return None

        title_section = response.find("div", {"class": "episodes"})
        if not title_section:
            logger.error("Could not extract title")
            return None
        if not (isinstance(title_section, Tag) and title_section.h1):
            logger.error("Could not extract title")
            return None
        stream.name = title_section.h1.text
        return stream

    def get_seasonal_streams(self, **kwargs: Any) -> list[UnprocessedStream]:
        # What is this for again ?
        return []

    def get_stream_link(self, stream: Stream) -> str:
        return self._show_url.format(id=stream.show_key)

    def extract_show_key(self, url: str) -> str | None:
        if match := self._show_re.search(url):
            return match.group(1)
        return None

    def _is_valid_episode(
        self, episode: Episode, show_key: str, **kwargs: Any
    ) -> Episode | None:
        # Possibly other cases to watch ?
        response = self.request_html(url=episode.link, **kwargs)
        if not response:
            logger.error("Invalid episode link for show %s/%s", self.key, show_key)
            return None
        if not (match := self._date_re.search(str(response.h2 or ""))):
            logger.warning("Date not found")
            return episode
        month, day, year = map(int, match.groups())
        # HIDIVE only has m/d/y, not hh:mm
        episode_day = datetime(day=day, month=month, year=year)
        date_diff = datetime.utcnow() - episode_day
        if date_diff >= timedelta(days=2):
            logger.debug("  Episode too old")
            return None
        episode.date = episode_day
        return episode


_episode_re = re.compile(
    r"(?:https://www.hidive.com)?/stream/[\w-]+/s\d{2}e(\d{3})", re.I
)
_episode_re_alter = re.compile(
    r"(?:https://www.hidive.com)?/stream/[\w-]+/\d{4}\d{2}\d{2}(\d{2})", re.I
)
_episode_name_correct = re.compile(r"(?:E\d+|Shorts) ?\| ?(.*)")
_episode_name_invalid = re.compile(r".*coming soon.*", re.I)
_episode_link = "https://www.hidive.com{href}"


def _preprocess_episode(feed_episode: Tag) -> Episode | None:
    logger.debug("Pre-processing episode")
    if not feed_episode.a:
        return None
    episode_link = _episode_link.format(href=feed_episode.a["href"])

    # Get data
    num_match = _episode_re.match(episode_link)
    num_match_alter = _episode_re_alter.match(episode_link)
    if num_match:
        num = int(num_match.group(1))
    elif num_match_alter:
        logger.warning("Using alternate episode key format")
        num = int(num_match_alter.group(1))
    else:
        logger.warning("Unknown episode number format in %s", episode_link)
        return None
    if num <= 0:
        return None

    if not feed_episode.h2:
        name = ""
    else:
        name = feed_episode.h2.text

    if name_match := _episode_name_correct.match(name):
        logger.debug("  Corrected title from %s", name)
        name = name_match.group(1)
    if _episode_name_invalid.match(name):
        logger.warning("  Episode title not found")
        name = ""

    date = datetime.utcnow()  # Not included in stream !

    return Episode(number=num, name=name, link=episode_link, date=date)
