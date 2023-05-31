# API information
# 	https://myanimelist.net/apiconfig/references/api/v2

import re
import logging
from typing import Any
from xml.etree import ElementTree as xml_parser

from data.models import Link, Show, ShowType, UnprocessedShow

from .. import AbstractInfoHandler

logger = logging.getLogger(__name__)


class InfoHandler(AbstractInfoHandler):
	_show_link_base = "https://myanimelist.net/anime/{id}/"
	_show_link_matcher = r"https?://(?:.+?\.)?myanimelist\.net/anime/([0-9]+)"
	_season_show_url = r"https://myanimelist.net/anime/season"

	_api_search_base = "https://myanimelist.net/api/anime/search.xml?q={q}"
	# TODO: deprecated API, change to use v2 instead.

	def __init__(self) -> None:
		super().__init__(key="mal", name="MyAnimeList")

	def get_link(self, link: Link | None) -> str | None:
		if link is None:
			return None
		return self._show_link_base.format(id=link.site_key)

	def extract_show_id(self, url: str | None) -> str | None:
		if url is None:
			return None
		if match := re.match(self._show_link_matcher, url, re.I):
			return match.group(1)
		return None

	def find_show(self, show_name: str, **kwargs: Any) -> list[UnprocessedShow]:
		url = self._api_search_base.format(q=show_name)
		result = self._mal_api_request(url, **kwargs)
		if result is None:
			logger.error("Failed to find show")
			return []

		assert result.tag == "anime"
		shows: list[UnprocessedShow] = []

		for child in result:
			print(child)
			assert child.tag == "entry"

			try:
				id: str = child.find("id").text
				name: str = child.find("title").text
				more_names: list[str] = [child.find("english").text]
			except AttributeError:
				logger.error("Malformed MAL entry: required tags are missing.")
				return []

			show = UnprocessedShow(
				site_key=self.key,
				show_key=id,
				name=name,
				more_names=more_names,
				show_type=ShowType.UNKNOWN,
			)
			shows.append(show)

		return shows

	def find_show_info(self, show_id: str, **kwargs: Any) -> UnprocessedShow | None:
		logger.debug("Getting show info for %s", show_id)

		# Request show page from MAL
		url = self._show_link_base.format(id=show_id)
		response = self._mal_request(url, **kwargs)
		if response is None:
			logger.error("Cannot get show page")
			return None

		# Parse show page
		names_sib = response.find("h2", string="Alternative Titles")
		# English
		name_elem = names_sib.find_next_sibling("div")
		if name_elem is None:
			logger.warning("  Name elem not found")
			return None
		name_english = name_elem.string
		logger.info("  English: %s", name_english)

		names = [name_english]
		return UnprocessedShow(
			site_key=self.key,
			show_key=show_id,
			name=name_english,
			more_names=names,
			show_type=ShowType.UNKNOWN,
		)

	def get_episode_count(self, link: Link, **kwargs: Any):
		logger.debug("Getting episode count")

		# Request show page from MAL
		url = self._show_link_base.format(id=link.site_key)
		response = self._mal_request(url, **kwargs)
		if response is None:
			logger.error("Cannot get show page")
			return None

		# Parse show page (ugh, HTML parsing)
		count_sib = response.find("span", string="Episodes:")
		if count_sib is None:
			logger.error("Failed to find episode count sibling")
			return None
		count_elem = count_sib.find_next_sibling(string=re.compile(r"\d+"))
		if count_elem is None:
			logger.warning("  Count not found")
			return None
		count = int(count_elem.strip())
		logger.debug("  Count: %s", count)

		return count

	def get_show_score(self, show: Show, link: Link, **kwargs: Any) -> float | None:
		logger.debug("Getting show score")

		# Request show page
		url = self._show_link_base.format(id=link.site_key)
		response = self._mal_request(url, **kwargs)
		if response is None:
			logger.error("Cannot get show page")
			return None

		# Find score
		score_elem = response.find("span", attrs={"itemprop": "ratingValue"})
		try:
			score = float(score_elem.string)
		except AttributeError:
			logger.warning("  Count not found")
			return None
		logger.debug("  Score: %s", score)

		return score

	def get_seasonal_shows(
		self, year: int | None = None, season: str | None = None, **kwargs: Any
	) -> list[UnprocessedShow]:
		# TODO: use year and season if provided
		logger.debug("Getting season shows: year=%s, season=%s", year, season)

		# Request season page from MAL
		response = self._mal_request(self._season_show_url, **kwargs)
		if response is None:
			logger.error("Cannot get show list")
			return []

		# Parse page (ugh, HTML parsing. Where's the useful API, MAL?)
		lists = response.find_all(class_="seasonal-anime-list")
		if len(lists) == 0:
			logger.error("Invalid page? Lists not found")
			return []
		new_list = lists[0].find_all(class_="seasonal-anime")
		if len(new_list) == 0:
			logger.error("Invalid page? Shows not found in list")
			return []

		new_shows: list[UnprocessedShow] = []
		episode_count_regex = re.compile(r"(\d+|\?) eps?")
		for show in new_list:
			show_key = show.find(class_="genres")["id"]
			title = str(show.find("a", class_="link-title").string)
			title = _normalize_title(title)
			more_names = [title[:-11]] if title.lower().endswith("2nd season") else []
			show_type = ShowType.TV  # TODO, changes based on section/list
			try:
				episode_count = int(
					episode_count_regex.search(
						show.find(class_="eps").find(string=episode_count_regex)
					).group(1)
				)
			except (AttributeError, ValueError):
				episode_count = 0
			has_source = show.find(class_="source").string != "Original"

			new_shows.append(
				UnprocessedShow(
					site_key=self.key,
					show_key=show_key,
					name=title,
					more_names=more_names,
					show_type=show_type,
					episode_count=episode_count,
					has_source=has_source,
				)
			)

		return new_shows

	# Private

	def _mal_request(self, url: str, **kwargs: Any) -> Any:
		return self.request_html(url=url, **kwargs)

	def _mal_api_request(self, url: str, **kwargs: Any) -> xml_parser.Element | None:
		if (
			self.config is None
			or "username" not in self.config
			or "password" not in self.config
		):
			logger.error("Username and password required for MAL requests")
			return None

		auth = (self.config["username"], self.config["password"])
		return self.request_xml(url=url, auth=auth, **kwargs)


def _convert_type(mal_type: str) -> ShowType:
	mal_type = mal_type.lower()
	if mal_type == "tv":
		return ShowType.TV
	if mal_type == "movie":
		return ShowType.MOVIE
	if mal_type == "ova":
		return ShowType.OVA
	return ShowType.UNKNOWN


def _normalize_title(title: str) -> str:
	title = re.sub(r" \(TV\)", "", title)
	return title
