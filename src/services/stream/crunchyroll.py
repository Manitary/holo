import re
from datetime import datetime, timedelta

from .. import AbstractServiceHandler
from data.models import Episode, UnprocessedStream
import logging

logger = logging.getLogger(__name__)

class ServiceHandler(AbstractServiceHandler):
    _show_url = "http://crunchyroll.com/{id}"
    _show_re = re.compile("crunchyroll.com/([\w-]+)", re.I)
    _episode_rss = "http://crunchyroll.com/{id}.rss"
    _backup_rss = "http://crunchyroll.com/rss/anime"
    _season_url = "http://crunchyroll.com/lineup"

    def __init__(self):
        super().__init__("crunchyroll", "Crunchyroll", False)

    # Episode finding

    def get_all_episodes(self, stream, **kwargs):
        logger.info("Getting live episodes for Crunchyroll/{}".format(stream.show_key))
        episode_datas = self._get_feed_episodes(stream.show_key, **kwargs)

        # Check data validity and digest
        episodes = []
        for episode_data in episode_datas:
            if _is_valid_episode(episode_data, stream.show_key):
                try:
                    episodes.append(_digest_episode(episode_data))
                except:
                    logger.exception(
                        "Problem digesting episode for Crunchyroll/{}".format(
                            stream.show_key
                        )
                    )

        if len(episode_datas) > 0:
            logger.debug(
                "  {} episodes found, {} valid".format(
                    len(episode_datas), len(episodes)
                )
            )
        else:
            logger.debug("  No episodes found")
        return episodes

    def _get_feed_episodes(self, show_key, **kwargs):
        """
        Always returns a list.
        """
        logger.info("Getting episodes for Crunchyroll/{}".format(show_key))

        url = self._get_feed_url(show_key)

        # Send request
        response = self.request(url, rss=True, **kwargs)
        if response is None:
            logger.error("Cannot get latest show for Crunchyroll/{}".format(show_key))
            return list()

        # Parse RSS feed
        if not _verify_feed(response):
            logger.warning("Parsed feed could not be verified, may have unexpected results")
        return response.get("entries", list())

    @classmethod
    def _get_feed_url(cls, show_key):
        # Sometimes shows don't have an RSS feed
        # Use the backup global feed when it doesn't
        if show_key is not None:
            return cls._episode_rss.format(id=show_key)
        else:
            logger.debug("  Using backup feed")
            return cls._backup_rss

    # Remote info getting

    _title_fix = re.compile("(.*) Episodes", re.I)
    _title_fix_fr = re.compile("(.*) Épisodes", re.I)

    def get_stream_info(self, stream, **kwargs):
        logger.info("Getting stream info for Crunchyroll/{}".format(stream.show_key))

        url = self._get_feed_url(stream.show_key)
        response = self.request(url, rss=True, **kwargs)
        if response is None:
            logger.error("Cannot get feed")
            return None

        if not _verify_feed(response):
            logger.warning("Parsed feed could not be verified, may have unexpected results")

        stream.name = response.feed.title
        match = self._title_fix.match(stream.name)
        if match:
            stream.name = match.group(1)
        match = self._title_fix_fr.match(stream.name)
        if match:
            stream.name = match.group(1)
        return stream

    def get_seasonal_streams(self, **kwargs):
        logger.debug("Getting season shows")

        # Request page
        response = self.request(self._season_url, html=True, **kwargs)
        if response is None:
            logger.error("Failed to get seasonal streams page")
            return list()

        # Find sections (continuing simulcast, new simulcast, new catalog)
        lists = response.find_all(class_="lineup-grid")
        if len(lists) < 2:
            logger.error("Unsupported structure of lineup page")
            return list()
        elif len(lists) < 2 or len(lists) > 3:
            logger.warning("Unexpected number of lineup grids")

        # Parse individual shows
        # WARNING: Some may be dramas and there's nothing distinguishing them from anime
        show_elements = lists[1].find_all(class_="element-lineup-anime")
        raw_streams = list()
        for show in show_elements:
            title = show["title"]
            if "to be announced" not in title.lower():
                logger.debug("  Show: {}".format(title))
                url = show["href"]
                logger.debug("  URL: {}".format(url))
                url_match = self._show_re.search(url)
                if not url_match:
                    logger.error("Failed to parse show URL: {}".format(url))
                    continue
                key = url_match.group(1)
                logger.debug("  Key: {}".format(key))
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

    def _get_stream_info(self, show_key):
        # TODO: load show page and figure out offsets based on contents
        return 0, 0

    # Local info formatting

    def get_stream_link(self, stream):
        # Just going to assume it's the correct service
        return self._show_url.format(id=stream.show_key)

    def extract_show_key(self, url):
        match = self._show_re.search(url)
        if match:
            if match.group(1) != "series":
                return match.group(1)
        return None


# Episode feeds


def _verify_feed(feed):
    logger.debug("Verifying feed")
    if feed.bozo:
        logger.debug("  Feed was malformed")
        return False
    if (
        "crunchyroll" not in feed.namespaces
        or feed.namespaces["crunchyroll"] != "http://www.crunchyroll.com/rss"
    ):
        logger.debug("  Crunchyroll namespace not found or invalid")
        return False
    if feed.feed.language != "en-us":
        logger.debug("  Language not en-us")
        return False
    logger.debug("  Feed verified")
    return True


def _is_valid_episode(feed_episode, show_id):
    # We don't want non-episodes (PVs, VA interviews, etc.)
    if feed_episode.get("crunchyroll_isclip", False) or not hasattr(
        feed_episode, "crunchyroll_episodenumber"
    ):
        logger.debug("Is PV, ignoring")
        return False
    # Don't check really old episodes
    episode_date = datetime(*feed_episode.published_parsed[:6])
    date_diff = datetime.utcnow() - episode_date
    if date_diff >= timedelta(days=2):
        logger.debug("  Episode too old")
        return False
    return True


_episode_name_correct = re.compile("Episode \d+ - (.*)")
_episode_count_fix = re.compile("([0-9]+)[abc]?", re.I)


def _digest_episode(feed_episode):
    logger.debug("Digesting episode")

    # Get data
    num_match = _episode_count_fix.match(feed_episode.crunchyroll_episodenumber)
    if num_match:
        num = int(num_match.group(1))
    else:
        logger.warning(
            'Unknown episode number format "{}"'.format(
                feed_episode.crunchyroll_episodenumber
            )
        )
        num = 0
    logger.debug("  num={}".format(num))
    name = feed_episode.title
    match = _episode_name_correct.match(name)
    if match:
        logger.debug('  Corrected title from "{}"'.format(name))
        name = match.group(1)
    logger.debug("  name={}".format(name))
    link = feed_episode.link
    logger.debug("  link={}".format(link))
    date = feed_episode.published_parsed
    logger.debug("  date={}".format(date))

    return Episode(number=num, name=name, link=link, date=date)


_slug_regex = re.compile("crunchyroll.com/([a-z0-9-]+)/", re.I)


def _get_slug(episode_link):
    match = _slug_regex.search(episode_link)
    if match:
        return match.group(1)
    return None


# Season page
