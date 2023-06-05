import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from data.models import Episode, Stream, UnprocessedStream

from .. import AbstractServiceHandler

logger = logging.getLogger(__name__)


@dataclass
class HuluDataEpisode:
	name: str = ""
	date: datetime = datetime.utcnow()
	season: int = 0
	number: int = 0
	series_name: str = ""


@dataclass
class HuluData:
	show_id: str = ""
	latest_season: int = 0
	title: str = ""
	internal_id: str = ""
	episodes: list[HuluDataEpisode] = field(default_factory=list)


class InvalidHuluException(Exception):
	"""Generic exception raised when parsing the contents of a Hulu webpage."""


class ServiceHandler(AbstractServiceHandler):
	_show_url = "http://hulu.com/series/{id}"
	_show_url_from_config = re.compile(r"season-\d+-(.*)$")
	_show_season_from_key = re.compile(r"season-(\d+)-.*")
	_show_id_from_key = re.compile(r"season-\d+-((?:\w-?)+)")
	_show_re = re.compile(r"hulu\.com\/series\/((?:\w-?)+)")
	_show_data_json = re.compile(
		r"<script id=\"__NEXT_DATA__\" type=\"application\/json\">(.+?)<\/script>"
	)

	def __init__(self) -> None:
		super().__init__(key="hulu", name="Hulu", is_generic=False)

	def get_all_episodes(self, stream: Stream, **kwargs: Any) -> Iterable[Episode]:
		logger.info("Getting live episodes for Hulu/%s", stream.show_key)
		match = self._show_season_from_key.match(stream.show_key)
		season_number = int(match.group(1)) if match else 1
		episode_datas = self._get_feed_episodes(stream.show_key)
		if not episode_datas:
			logger.error("Could not fetch data for Hulu/%s", stream.show_key)
			return []
		episode_datas = list(map(_adjust_date, episode_datas))

		episodes = [
			Episode(number=e.number, name=e.name, link="", date=e.date)
			for e in episode_datas
			if _is_valid_episode(episode=e, season=season_number)
		]
		logger.debug(" .. %s episodes found", len(episodes))

		return episodes

	def get_stream_link(self, stream: Stream) -> str:
		return self._get_feed_url(stream.show_key)

	def extract_show_key(self, url: str) -> str | None:
		# Get the season number if provided
		if match := self._show_season_from_key.match(url):
			season_number = int(match.group(1))
		else:
			season_number = 1
		# Remove the season prefix if it exists
		if match := self._show_url_from_config.match(url):
			url = match.group(1)
		# Extract the key from the URL
		match = self._show_re.search(url)
		if not match:
			return None
		series_key = match.group(1)
		full_key = f"season-{season_number}-{series_key}"
		return full_key


	def get_stream_info(self, stream: Stream, **kwargs: Any) -> Stream | None:
		logger.info("Getting stream info for Hulu/%s", stream.show_key)
		url = self._get_feed_url(stream.show_key)
		match = self._show_season_from_key.match(stream.show_key)
		season_number = int(match.group(1)) if match else 1
		match = self._show_re.search(url)
		if not match:
			logger.error("Malformed show key")
			return None

		series_key = match.group(1)

		response = self.request_text(url=url, **kwargs)
		if not response:
			logger.error("Cannot get feed")
			return None

		try:
			contents_json = self._get_json_data(response)
		except (InvalidHuluException, json.JSONDecodeError):
			logger.error("Could not extract contents of url %s.", url)
			return None

		try:
			series_name = _validate_feed(
				contents_json=contents_json,
				series_key=series_key,
				season_number=season_number,
			)
		except (KeyError, TypeError, ValueError):
			logger.error("Malformed feed.")
			return None

		if not series_name:
			logger.error("Could not verify feed.")
			return None

		stream.name = series_name
		return stream

	def get_seasonal_streams(self, **kwargs: Any) -> list[UnprocessedStream]:
		# Not used
		return []

	def _get_feed_episodes(self, show_key: str) -> list[HuluDataEpisode] | None:
		logger.info("Getting episodes for Hulu/%s", show_key)
		url = self._get_feed_url(show_key)
		season = self._get_season_number(show_key)
		response = self.request_text(url=url)
		if not response:
			logger.error("Cannot get latest show for Hulu/%s", show_key)
			return None

		try:
			contents_json = self._get_json_data(response)
		except (InvalidHuluException, json.JSONDecodeError):
			logger.error("Cannot get series JSON data for Hulu/%s", show_key)
			return None

		try:
			data = _validate_contents(contents_json)
		except (
			InvalidHuluException,
			KeyError,
			TypeError,
			ValueError,
			StopIteration,
		) as e:
			logger.error(
				"Cannot parse JSON data for Hulu/%s. An exception has occurred: %s",
				show_key,
				e,
			)
			return None

		if season != data.latest_season:
			logger.warning(
				(
					"Requesting data from season %s when the latest season is %s. "
					"Verify that the show key is correct: %s"
				),
				season,
				data.latest_season,
				show_key,
			)

		return data.episodes

	@classmethod
	def _get_feed_url(cls, show_key: str) -> str:
		match = cls._show_id_from_key.match(show_key)
		show_id = match.group(1) if match else show_key
		return cls._show_url.format(id=show_id)

	def _get_season_number(self, show_key: str) -> int:
		match = self._show_season_from_key.match(show_key)
		season_number = int(match.group(1)) if match else 1
		return season_number

	def _get_json_data(self, response_text: str) -> Any:
		contents = re.findall(self._show_data_json, response_text)
		if not contents:
			raise InvalidHuluException
		if len(contents) > 1:
			logger.warning(
				"Multiple matches found, may have unexpected results. The first match will be used."
			)
		contents_json = json.loads(contents[0])
		return contents_json


def _validate_feed(contents_json: Any, series_key: str, season_number: int) -> str:
	page = contents_json["props"]["pageProps"]
	show_id: str = page["query"]["id"]
	if show_id != series_key:
		logger.warning(
			"  The provided show key (%s) does not match the website (%s); this should never happen",
			series_key,
			show_id,
		)
	latest_season: int = int(page["latestSeason"]["season"])
	if latest_season != season_number:
		logger.warning(
			"  The provided season (%s) does not match the latest season available from the website (%s)",
			season_number,
			latest_season,
		)
	if page["layout"]["locale"].lower() != "en-us":
		logger.warning("  Language not en-us")
	components = page["layout"]["components"]
	for component in components:
		if component["type"] == "detailentity_masthead":
			title: str = component["title"]
			return title

	return ""


def _validate_contents(contents_json: Any) -> HuluData:
	page = contents_json["props"]["pageProps"]
	show_id: str = page["query"]["id"]
	latest_season: int = int(page["latestSeason"]["season"])
	if page["layout"]["locale"].lower() != "en-us":
		logger.warning("Unexpected language detected, may have unexpected results")
	components = page["layout"]["components"]
	episode_container: list[dict[str, str]] = []
	title, internal_id = "", ""
	for component in components:
		if component["type"] == "detailentity_masthead":
			title: str = component["title"]
			internal_id: str = component["entityId"]
		elif component["type"] == "collection_tabs":
			episode_container = next(
				(
					tab["model"]["collection"]["items"]
					for tab in component["tabs"]
					if tab["title"] == "Episodes"
				),
				episode_container,
			)
	if not episode_container:
		raise InvalidHuluException
	episodes = list(
		filter(
			None,
			[_format_episode_from_json(episode) for episode in episode_container],
		)
	)
	series_data = HuluData(
		show_id=show_id,
		latest_season=latest_season,
		title=title,
		internal_id=internal_id,
		episodes=episodes,
	)
	return series_data


def _format_episode_from_json(episode_json: dict[str, str]) -> HuluDataEpisode | None:
	name = episode_json["name"]
	date = episode_json["premiereDate"]
	season = int(episode_json["season"])
	number = int(episode_json["number"])
	series_name = episode_json["seriesName"]
	if name.lower().startswith("(dub)"):
		return None
	if name.lower().startswith("(sub)"):
		name = name[6:]
	formatted_episode = HuluDataEpisode(
		name=name,
		date=datetime.fromisoformat(date).replace(tzinfo=None),
		season=season,
		number=number,
		series_name=series_name,
	)
	return formatted_episode


_time_adjustments = {
	"Tengoku Daimakyo": timedelta(hours=1),  # 12pm UTC -> 1pm UTC
}


def _adjust_date(episode: HuluDataEpisode) -> HuluDataEpisode:
	episode.date += _time_adjustments.get(episode.series_name, timedelta(0))
	return episode


def _is_valid_episode(episode: HuluDataEpisode, season: int) -> bool:
	date_diff = datetime.utcnow() - episode.date
	if date_diff >= timedelta(days=2):
		logger.debug("  Episode S%sE%s too old", episode.season, episode.number)
		return False
	if season != episode.season:
		logger.warning("Mismatch between expected season %s and episode %s", season, episode)
	return True
