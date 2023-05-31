# Dummy info handler, used for official website of shows


from typing import Any
from data.models import Link, Show, UnprocessedShow
from .. import AbstractInfoHandler


class InfoHandler(AbstractInfoHandler):
	def __init__(self) -> None:
		super().__init__("official", "Official Website")

	def get_link(self, link: Link | None) -> str | None:
		if link is None:
			return None
		return link.site_key

	def extract_show_id(self, url: str | None) -> str | None:
		return url

	def find_show(self, show_name: str, **kwargs: Any) -> list[Show]:
		return []

	def find_show_info(self, show_id: str, **kwargs: Any) -> None:
		return None

	def get_episode_count(self, link: Link, **kwargs: Any) -> None:
		return None

	def get_show_score(self, show: Show, link: Link, **kwargs: Any) -> None:
		return None

	def get_seasonal_shows(
		self, year: int | None = None, season: str | None = None, **kwargs: Any
	) -> list[UnprocessedShow]:
		return []
