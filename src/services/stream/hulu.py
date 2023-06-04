from datetime import datetime
import logging
import re
from typing import Any, Iterable

from bs4 import BeautifulSoup, Tag
from data.models import Episode, Stream, UnprocessedStream

from .. import AbstractServiceHandler

logger = logging.getLogger(__name__)


# 03/06/2023
# The webpage is loaded with scripts
# Basic html scraping can only retrieve title of the series and number of episodes
# Individual episode numbers and titles can be obtained with e.g. selenium
# but not release date (might need subscription to access individual episode pages?)


class ServiceHandler(AbstractServiceHandler):
	# 03/06/2023 Format: series-title-followed-by-hash-hash-hash-hash-hash (5 times)
	# _show_re = re.compile(r"hulu\.com\/series\/((?:\w-?)+)(?:-\w+){5}")
	# However, it does not allow to reconstruct the URL
	_show_re = re.compile(r"hulu\.com\/series\/((?:\w-?)+)")

	def __init__(self) -> None:
		super().__init__(key="hulu", name="Hulu", is_generic=False)

	def get_all_episodes(self, stream: Stream, **kwargs: Any) -> Iterable[Episode]:
		logger.info("Getting live episodes for Hulu/%s", stream.show_key)
		episode_data = self._get_feed_episodes(stream.show_key)
		if not episode_data:
			logger.error("Could not fetch data for Hulu/%s", stream.show_key)
			return []
		episodes = [
			Episode(number=i, name="", link="", date=datetime.utcnow())
			for i in range(1, episode_data[1] + 1)
		]
		logger.debug(" .. %s episodes found", len(episodes))

		return episodes

	def get_stream_link(self, stream: Stream) -> str | None:
		# Impossible without knowing the URL
		return None

	def extract_show_key(self, url: str) -> str | None:
		if match := self._show_re.search(url):
			return match.group(1)
		return None

	def get_stream_info(self, stream: Stream, **kwargs: Any) -> Stream | None:
		return None

	def get_seasonal_streams(self, **kwargs: Any) -> list[UnprocessedStream]:
		# Not used
		return []

	def _get_feed_episodes(self, show_key: str) -> tuple[str, int] | None:
		logger.info("Getting episodes for Hulu/%s", show_key)
		url = self._get_feed_url(show_key)

		response = self.request_html(url=url)
		if not response:
			logger.error("Cannot get latest show for Hulu/%s", show_key)
			return None

		num_episodes = _get_number_of_episodes(response)
		series_name = _get_series_name(response)

		if not (num_episodes and series_name):
			logger.error("Parsed feed is not valid.")
			return None

		return series_name, num_episodes

	@classmethod
	def _get_feed_url(cls, show_key: str) -> str:
		return f"https://www.hulu.com/series/{show_key}"


def _get_number_of_episodes(response: BeautifulSoup) -> int:
	pattern = re.compile(r"(\d+) episodes?")

	def f(tag: Tag) -> bool:
		p = tag.parent
		if not p:
			return False
		return (
			tag.name == "span"
			and p.name == "div"
			and p.has_attr("class")
			and "DetailEntityMasthead__headline" in p["class"]
		)

	def to_int(match: re.Match[str]) -> int:
		return int(match.group(1))

	possible_valid = list(
		map(
			to_int,
			filter(None, [pattern.search(tag.text) for tag in response.find_all(f)]),
		)
	)

	if not possible_valid:
		return 0
	if len(possible_valid) == 1:
		return possible_valid[0]
	logger.warning("Multiple possible number of episodes found: %s", possible_valid)
	return max(possible_valid)


_invalid_series_name = {
	"you may also like",
	"select your plan",
	"next stop: shop hulu, powered by snowcommerce",
}


def _get_series_name(response: BeautifulSoup) -> str:
	# 03/06/2023 The series name should be the text of the first h2 tag
	possible_valid = [
		t
		for tag in response.find_all("h2")
		if (t := tag.text) not in _invalid_series_name
	]
	if not possible_valid:
		logger.error("Series name not found")
		return ""
	if len(possible_valid) > 1:
		logger.warning(
			"Multiple possible series name found, may have unexpected results. Using %s",
			possible_valid[0],
		)
	return possible_valid[0]
