import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from ...data.feeds import CrunchyrollEntry, CrunchyrollPayload
from ...data.models import Episode, Stream, UnprocessedStream
from .. import AbstractServiceHandler

logger = logging.getLogger(__name__)


class ServiceHandler(AbstractServiceHandler):
    _show_url = "http://crunchyroll.com/{id}"
    _show_re = re.compile(r"crunchyroll.com/([\w-]+)", re.I)
    _episode_rss = "http://crunchyroll.com/{id}.rss?lang=en-us"
    _backup_rss = r"http://crunchyroll.com/rss/anime"
    _season_url = r"http://crunchyroll.com/lineup"

    def __init__(self) -> None:
        super().__init__(key="crunchyroll", name="Crunchyroll", is_generic=False)

    # Episode finding

    def get_all_episodes(self, stream: Stream, **kwargs: Any) -> list[Episode]:
        logger.info("Getting live episodes for Crunchyroll/%s", stream.show_key)
        episode_datas = self._get_feed_episodes(stream.show_key, **kwargs)

        # Check data validity and digest
        episodes: list[Episode] = []
        for episode_data in episode_datas:
            if _is_valid_episode(episode_data):
                try:
                    episodes.append(_digest_episode(episode_data))
                except Exception:
                    logger.exception(
                        "Problem digesting episode for Crunchyroll/%s", stream.show_key
                    )
        logger.debug("  %d episodes found, %d valid", len(episode_datas), len(episodes))
        return episodes

    def _get_feed_episodes(
        self, show_key: str, **kwargs: Any
    ) -> list[CrunchyrollEntry]:
        """
        Always returns a list.
        """
        logger.info("Getting episodes for Crunchyroll/%s", show_key)

        url = self._get_feed_url(show_key)

        # Send request
        response: CrunchyrollPayload = self.request_rss(url, **kwargs)  # type:ignore
        if not response:
            logger.error("Cannot get latest show for Crunchyroll/%s", show_key)
            return []

        # Parse RSS feed
        if not _verify_feed(response):
            logger.warning(
                "Parsed feed could not be verified, may have unexpected results"
            )
        return response.get("entries", [])

    @classmethod
    def _get_feed_url(cls, show_key: str) -> str:
        # Sometimes shows don't have an RSS feed
        # Use the backup global feed when it doesn't
        if show_key:
            return cls._episode_rss.format(id=show_key)
        logger.debug("  Using backup feed")
        return cls._backup_rss

    # Remote info getting

    _title_fix = re.compile(r"(.*) E|Épisodes", re.I)

    def get_stream_info(self, stream: Stream, **kwargs: Any) -> Stream | None:
        logger.info("Getting stream info for Crunchyroll/%s", stream.show_key)

        url = self._get_feed_url(stream.show_key)
        response: CrunchyrollPayload = self.request_rss(url=url, **kwargs)  # type: ignore
        if not response:
            logger.error("Cannot get feed")
            return None

        if not _verify_feed(response):
            logger.warning(
                "Parsed feed could not be verified, may have unexpected results"
            )

        stream.name = response["feed"]["title"]
        if match := self._title_fix.match(stream.name):
            stream.name = match.group(1)
        return stream

    def get_seasonal_streams(self, **kwargs: Any) -> list[UnprocessedStream]:
        logger.debug("Getting season shows")

        # Request page
        response = self.request_html(self._season_url, **kwargs)
        if not response:
            logger.error("Failed to get seasonal streams page")
            return []

        # Find sections (continuing simulcast, new simulcast, new catalog)
        lists = response.find_all(class_="lineup-grid")
        if len(lists) < 2:
            logger.error("Unsupported structure of lineup page")
            return []
        if len(lists) > 3:
            logger.warning("Unexpected number of lineup grids")

        # Parse individual shows
        # WARNING: Some may be dramas and there's nothing distinguishing them from anime
        show_elements = lists[1].find_all(class_="element-lineup-anime")
        raw_streams: list[UnprocessedStream] = []
        for show in show_elements:
            title: str = show["title"]
            if "to be announced" not in title.lower():
                logger.debug("  Show: %s", title)
                url: str = show["href"]
                logger.debug("  URL: %s", url)
                url_match = self._show_re.search(url)
                if not url_match:
                    logger.error("Failed to parse show URL: %s", url)
                    continue
                key: str = url_match.group(1)
                logger.debug("  Key: %s", key)
                remote_offset, display_offset = self._get_stream_info(key)

                raw_stream = UnprocessedStream(
                    service_key=self.key,
                    show_key=key,
                    remote_offset=remote_offset,
                    display_offset=display_offset,
                    name=title,
                )
                raw_streams.append(raw_stream)

        return raw_streams

    def _get_stream_info(self, show_key: str) -> tuple[int, int]:
        # TODO: load show page and figure out offsets based on contents
        return 0, 0

    # Local info formatting

    def get_stream_link(self, stream: Stream) -> str:
        # Just going to assume it's the correct service
        return self._show_url.format(id=stream.show_key)

    def extract_show_key(self, url: str) -> str | None:
        if (match := self._show_re.search(url)) and match.group(1) != "series":
            return match.group(1)
        return None


# Episode feeds


def _verify_feed(feed: CrunchyrollPayload) -> bool:
    logger.debug("Verifying feed")
    if feed["bozo"]:
        logger.debug("  Feed was malformed")
        return False
    if feed["namespaces"].get("crunchyroll", "") != "http://www.crunchyroll.com/rss":
        logger.debug("  Crunchyroll namespace not found or invalid")
        return False
    if feed["feed"]["language"] != "en-us":
        logger.debug("  Language not en-us")
        return False
    if "entries" not in feed:
        logger.debug("  Invalid feed: missing 'entries' field")
        return False
    logger.debug("  Feed verified")
    return True


def _is_valid_episode(feed_episode: CrunchyrollEntry) -> bool:
    # We don't want non-episodes (PVs, VA interviews, etc.)
    if feed_episode.get("crunchyroll_isclip", False) or not feed_episode.get(
        "crunchyroll_episodenumber", ""
    ):
        logger.debug("Is PV, ignoring")
        return False
    # Don't check really old episodes
    # episode_date = datetime(*feed_episode["published_parsed"][:6])
    # date_diff = datetime.now(UTC).replace(tzinfo=None) - episode_date
    # if date_diff >= timedelta(days=2):
    #     logger.debug("  Episode too old")
    #     return False
    return True


_episode_name_correct = re.compile(r"Episode \d+ - (.*)")
_episode_count_fix = re.compile(r"([0-9]+)[abc]?", re.I)


def _digest_episode(feed_episode: CrunchyrollEntry) -> Episode:
    logger.debug("Digesting episode")

    # Get data
    episode_number = feed_episode["crunchyroll_episodenumber"]
    if num_match := _episode_count_fix.match(episode_number):
        num = int(num_match.group(1))
    else:
        logger.warning('Unknown episode number format "%s"', episode_number)
        num = 0
    logger.debug("  num=%d", num)
    name = feed_episode["title"]
    if match := _episode_name_correct.match(name):
        logger.debug('  Corrected title from "%s"', name)
        name = match.group(1)
    logger.debug("  name=%s", name)
    link = feed_episode["link"]
    logger.debug("  link=%s", link)
    date = feed_episode["published_parsed"]
    logger.debug("  date=%s", date)

    return Episode(number=num, name=name, link=link, date=date)
