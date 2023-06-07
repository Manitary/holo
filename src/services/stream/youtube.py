import logging
import re
from datetime import datetime
from typing import Any

from data.models import Episode, Stream, UnprocessedStream

from .. import AbstractServiceHandler

logger = logging.getLogger(__name__)


class ServiceHandler(AbstractServiceHandler):
	_playlist_api_query = "https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults=50&playlistId={id}&key={key}"
	_videos_api_query = "https://youtube.googleapis.com/youtube/v3/videos?part=status&part=snippet&hl=en&id={id}&key={key}"
	_channel_url = "https://www.youtube.com/playlist?list={id}"
	_channel_re = re.compile(r"youtube\.com\/playlist\\\?list=([\w-]+)", re.I)

	def __init__(self) -> None:
		super().__init__(key="youtube", name="Youtube", is_generic=False)

	# Episode finding

	def get_all_episodes(self, stream: Stream, **kwargs: Any) -> list[Episode]:
		logger.info("Getting live episodes for Youtube/%s", stream.show_key)
		episode_datas = self._get_feed_episodes(stream.show_key, **kwargs)

		# Extract valid episodes from feed and digest
		episodes: list[Episode] = []
		for episode_data in episode_datas:
			if _is_valid_episode(episode_data, stream.show_key):
				try:
					episode = _digest_episode(episode_data)
					if episode is not None:
						episodes.append(episode)
				except Exception:
					logger.exception(
						"Problem digesting episode for Youtube/%s", stream.show_key
					)

		if not episode_datas:
			logger.debug("  No episodes found")

		logger.debug("  %d episodes found, %d valid", len(episode_datas), len(episodes))
		return episodes

	def _get_feed_episodes(self, show_key: str, **kwargs: Any) -> list[Any]:
		url = self._get_feed_url(show_key)
		if not url:
			logger.error("Cannot get feed url for Youtube/%s", show_key)
			return []

		# Request channel information
		response = self.request_json(url=url, **kwargs)
		if not response:
			logger.error("Cannot get episode feed for Youtube/%s", show_key)
			return []

		# Extract videos ids and build new query for all videos
		if not _verify_feed(response):
			logger.warning(
				"Parsed feed could not be verified, may have unexpected results"
			)
		feed = response.get("items", list())

		video_ids = [item["contentDetails"]["videoId"] for item in feed]
		url = self._get_videos_url(video_ids)

		# Request videos information
		response = self.request_json(url=url, **kwargs)
		if response is None:
			logger.error("Cannot get video information for Youtube/%s", show_key)
			return []

		# Return feed
		if not _verify_feed(response):
			logger.warning(
				"Parsed feed could not be verified, may have unexpected results"
			)
		return response.get("items", list())

	def _get_feed_url(self, show_key: str) -> str | None:
		# Show key is the channel ID
		if not self.config or not self.config.get("api_key"):
			logger.error("  Missing API key for access to Youtube channel")
			return None
		api_key = self.config["api_key"]
		if not show_key:
			return None
		return self._playlist_api_query.format(id=show_key, key=api_key)

	def _get_videos_url(self, video_ids: list[str]) -> str:
		# Videos ids is a list of all videos in feed
		if not self.config or not self.config.get("api_key", None):
			logger.error("  Missing API key for access to Youtube channel")
			return ""
		api_key = self.config["api_key"]
		if not video_ids:
			return ""
		return self._videos_api_query.format(id=",".join(video_ids), key=api_key)

	def get_stream_info(self, stream: Stream, **kwargs: Any) -> None:
		# Can't trust consistent stream naming, ignored
		return None

	def get_seasonal_streams(self, **kwargs: Any) -> list[UnprocessedStream]:
		# What is this for again ?
		return []

	def get_stream_link(self, stream: Stream) -> str:
		return self._channel_url.format(id=stream.show_key)

	def extract_show_key(self, url: str) -> str | None:
		match = self._channel_re.search(url)
		if match:
			return match.group(1)
		return None


# Episode feeds format


def _verify_feed(feed: Any) -> bool:
	logger.debug("Verifying feed")
	if feed["kind"] not in {
		"youtube#playlistItemListResponse",
		"youtube#videoListResponse",
	}:
		logger.debug("  Feed does not match request")
		return False
	if feed["pageInfo"]["totalResults"] > feed["pageInfo"]["resultsPerPage"]:
		logger.debug(
			"  Too many results (%s), will not get all episodes",
			feed["pageInfo"]["totalResults"],
		)
		return False
	logger.debug("  Feed verified")
	return True


_excludors = [
	re.compile(x, re.I)
	for x in [
		"(?:[^a-zA-Z]|^)(?:PV|OP|ED)(?:[^a-zA-Z]|$)",
		"blu.?ray",
		"preview",
	]
]

_num_extractors = [
	re.compile(x, re.I)
	for x in [
		r".*\D(\d{2,3})(?:\D|$)",
		r".*episode (\d+)(?:\D|$)",
		r".*S(?:\d+)E(\d+)(?:\D|$)",
	]
]


def _is_valid_episode(feed_episode: Any, show_id: str) -> bool:
	if feed_episode["status"]["privacyStatus"] == "private":
		logger.info("  Video was excluded (is private)")
		return False
	if feed_episode["snippet"]["liveBroadcastContent"] == "upcoming":
		logger.info("  Video was excluded (not yet online)")
		return False
	title: str = feed_episode["snippet"]["localized"]["title"]
	if not title:
		logger.info("  Video was excluded (no title found)")
		return False
	if any(ex.search(title) for ex in _excludors):
		logger.info("  Video was excluded (excludors)")
		return False
	if all(num.match(title) is None for num in _num_extractors):
		logger.info("  Video was excluded (no episode number found)")
		return False
	return True


def _digest_episode(feed_episode: Any) -> Episode | None:
	_video_url = "https://www.youtube.com/watch?v={video_id}"
	snippet = feed_episode["snippet"]

	title = snippet["localized"]["title"]
	episode_num = _extract_episode_num(title)
	if episode_num is None or not 0 < episode_num < 720:
		return None

	date_string = snippet["publishedAt"].replace("Z", "")
	# date_string = snippet["publishedAt"].replace('Z', '+00:00') # Use this for offset-aware dates
	date = datetime.fromisoformat(date_string) or datetime.utcnow()

	link = _video_url.format(video_id=feed_episode["id"])
	return Episode(number=episode_num, name="", link=link, date=date)


def _extract_episode_num(name: str) -> int | None:
	logger.debug('Extracting episode number from "%s"', name)
	if any(ex.search(name) is not None for ex in _excludors):
		return None
	for regex in _num_extractors:
		match = regex.match(name)
		if match:
			num = int(match.group(1))
			logger.debug("  Match found, num=%d", num)
			return num
	logger.debug("  No match found")
	return None
