import re
from datetime import datetime, timedelta

from .. import AbstractServiceHandler
from data.models import Episode, UnprocessedStream
import logging

logger = logging.getLogger(__name__)


class ServiceHandler(AbstractServiceHandler):
    _show_url = "https://www.hidive.com/tv/{id}"
    _show_re = re.compile("hidive.com/tv/([\w-]+)", re.I)

    def __init__(self):
        super().__init__("hidive", "HIDIVE", False)

    # Episode finding

    def get_all_episodes(self, stream, **kwargs):
        logger.info("Getting live episodes for HiDive/%s", stream.show_key)
        episode_datas = self._get_feed_episodes(stream.show_key, **kwargs)

        # Check episode validity and digest
        episodes = []
        for episode_data in episode_datas:
            if _is_valid_episode(episode_data, stream.show_key):
                try:
                    episode = _digest_episode(episode_data)
                    if episode is not None:
                        episodes.append(episode)
                except Exception:
                    logger.exception(
                        "Problem digesting episode for HiDive/%s", stream.show_key
                    )

        if len(episode_datas) > 0:
            logger.debug(
                "  %d episodes found, %d valid", len(episode_datas), len(episodes)
            )
        else:
            logger.debug("  No episode found")
        return episodes

    def _get_feed_episodes(self, show_key, **kwargs):
        logger.info("Getting episodes for HiDive/%s", show_key)

        url = self._get_feed_url(show_key)

        # Send request
        response = self.request(url, html=True, **kwargs)
        if response is None:
            logger.error("Cannot get show page for HiDive/%s", show_key)
            return list()

        # Parse html page
        sections = response.find_all("div", {"data-section": "episodes"})
        # return [section.a['data-playurl'] for section in sections if section.a]
        return sections

    @classmethod
    def _get_feed_url(cls, show_key):
        if show_key is not None:
            return cls._show_url.format(id=show_key)
        else:
            return None

    # Remove info getting

    def get_stream_info(self, stream, **kwargs):
        logger.info("Getting stream info for HiDive/%s", stream.show_key)

        url = self._get_feed_url(stream.show_key)
        response = self.request(url, html=True, **kwargs)
        if response is None:
            logger.error("Cannot get feed")
            return None

        title_section = response.find("div", {"class": "episodes"})
        if title_section is None:
            logger.error("Could not extract title")
            return None

        stream.name = title_section.h1.text
        return stream

    def get_seasonal_streams(self, **kwargs):
        # What is this for again ?
        return list()

    def get_stream_link(self, stream):
        return self._show_url.format(id=stream.show_key)

    def extract_show_key(self, url):
        match = self._show_re.search(url)
        if match:
            return match.group(1)
        return None


_episode_re = re.compile(
    "(?:https://www.hidive.com)?/stream/[\w-]+/s\d{2}e(\d{3})", re.I
)
_episode_re_alter = re.compile(
    "(?:https://www.hidive.com)?/stream/[\w-]+/\d{4}\d{2}\d{2}(\d{2})", re.I
)
_episode_name_correct = re.compile("(?:E\d+|Shorts) ?\| ?(.*)")
_episode_name_invalid = re.compile(".*coming soon.*", re.I)


def _is_valid_episode(episode_data, show_key):
    # Possibly other cases to watch ?
    if episode_data.a is None:
        return False
    # return re.match(_episode_re.format(id=show_key), episode_data) is not None

    return True


def _digest_episode(feed_episode):
    logger.debug("Digesting episode")

    episode_link = feed_episode.a["href"]

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

    name = feed_episode.h2.text
    name_match = _episode_name_correct.match(name)
    if name_match:
        logger.debug("  Corrected title from %s", name)
        name = name_match.group(1)
    if _episode_name_invalid.match(name):
        logger.warning("  Episode title not found")
        name = None

    link = episode_link
    date = datetime.utcnow()  # Not included in stream !

    return Episode(number=num, name=name, link=link, date=date)
