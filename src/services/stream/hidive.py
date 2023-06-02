import re
from datetime import datetime
import logging
from typing import Any, Protocol

from bs4 import ResultSet
from data.models import Episode, Stream, UnprocessedStream

from .. import AbstractServiceHandler

logger = logging.getLogger(__name__)

class Heading(Protocol):
	@property
	def text(self) -> str:
		...

class HIDIVEFeedEpisode(Protocol):
	@property
	def a(self) -> dict[str, str]:
		...

	@property
	def h1(self) -> Heading:
		...

	@property
	def h2(self) -> Heading:
		...

class ServiceHandler(AbstractServiceHandler):
	_show_url = "https://www.hidive.com/tv/{id}"
	_show_re = re.compile(r"hidive.com/tv/([\w-]+)", re.I)

	def __init__(self) -> None:
		super().__init__(key="hidive", name="HIDIVE", is_generic=False)

	# Episode finding

	def get_all_episodes(self, stream: Stream, **kwargs: Any) -> list[Episode]:
		logger.info("Getting live episodes for HiDive/%s", stream.show_key)
		episode_datas = self._get_feed_episodes(stream.show_key, **kwargs)
		if not episode_datas:
			logger.debug("  No episode found")
			return []
		# Check episode validity and digest
		episodes: list[Episode] = []
		for episode_data in episode_datas:
			if _is_valid_episode(episode_data, stream.show_key):
				try:
					episode = _digest_episode(episode_data)
					if episode is not None:
						episodes.append(episode)
				except Exception:
					logger.exception("Problem digesting episode for HiDive/%s", stream.show_key)

		logger.debug("  %s episodes found, %s valid", len(episode_datas), len(episodes))
		return episodes

	def _get_feed_episodes(self, show_key: str, **kwargs: Any) -> ResultSet[Any] | None:
		logger.info("Getting episodes for HiDive/%s", show_key)

		url = self._get_feed_url(show_key)

		# Send request
		response = self.request_html(url=url, **kwargs)
		if response is None:
			logger.error("Cannot get show page for HiDive/%s", show_key)
			return None

		# Parse html page
		sections = response.find_all("div", {"data-section": "episodes"})
		# return [section.a['data-playurl'] for section in sections if section.a]
		return sections

	@classmethod
	def _get_feed_url(cls, show_key: str) -> str:
		return cls._show_url.format(id=show_key)

	# Remove info getting

	def get_stream_info(self, stream: Stream, **kwargs: Any) -> Stream | None:
		logger.info("Getting stream info for HiDive/%s", stream.show_key)

		url = self._get_feed_url(stream.show_key)
		response = self.request_html(url=url, **kwargs)
		if response is None:
			logger.error("Cannot get feed")
			return None

		title_section = response.find("div", {"class": "episodes"})
		if title_section is None:
			logger.error("Could not extract title")
			return None

		stream.name = title_section.h1.text
		return stream

	def get_seasonal_streams(self, **kwargs: Any) -> list[UnprocessedStream]:
		return []

	def get_stream_link(self, stream: Stream) -> str:
		return self._show_url.format(id=stream.show_key)

	def extract_show_key(self, url: str) -> str | None:
		if match := self._show_re.search(url):
			return match.group(1)
		return None


_episode_re = re.compile(
	r"(?:https://www.hidive.com)?/stream/[\w-]+/s\d{2}e(\d{3})", re.I
)
_episode_re_alter = re.compile(
	r"(?:https://www.hidive.com)?/stream/[\w-]+/\d{4}\d{2}\d{2}(\d{2})", re.I
)
_episode_name_correct = re.compile(r"(?:E\d+|Shorts) ?\| ?(.*)")
_episode_name_invalid = re.compile(".*coming soon.*", re.I)


def _is_valid_episode(episode_data: HIDIVEFeedEpisode, show_key: str):
	# Possibly other cases to watch ?
	if not episode_data.a:
		return False
	# return re.match(_episode_re.format(id=show_key), episode_data) is not None

	return True


def _digest_episode(feed_episode: HIDIVEFeedEpisode) -> Episode | None:
	logger.debug("Digesting episode")

	episode_link: str = feed_episode.a["href"]

	# Get data
	if num_match := _episode_re.match(episode_link):
		num = int(num_match.group(1))
	elif num_match_alter := _episode_re_alter.match(episode_link):
		logger.warning("Using alternate episode key format")
		num = int(num_match_alter.group(1))
	else:
		logger.warning("Unknown episode number format in %s", episode_link)
		return None

	if num <= 0:
		return None

	name = feed_episode.h2.text

	if name_match := _episode_name_correct.match(name):
		logger.debug("  Corrected title from %s", name)
		name = name_match.group(1)

	if _episode_name_invalid.match(name):
		logger.warning("  Episode title not found")
		name = ""

	link = episode_link
	date = datetime.utcnow()  # Not included in stream !

	return Episode(number=num, name=name, link=link, date=date)
