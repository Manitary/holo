# Dummy info handler, used for official website of shows

import logging
import re
from typing import Any

from ...data.models import Link, Show, UnprocessedShow
from .. import AbstractInfoHandler

logger = logging.getLogger(__name__)


class InfoHandler(AbstractInfoHandler):
    _show_link_base = "/r/{id}"
    _show_link_matcher = r"/r/(\w+)"

    def __init__(self) -> None:
        super().__init__(key="subreddit", name="/r/")

    def get_link(self, link: Link | None) -> str | None:
        if not link:
            return None
        return self._show_link_base.format(id=link.site_key)

    def extract_show_id(self, url: str) -> str | None:
        if match := re.search(self._show_link_matcher, url, re.I):
            return match.group(1)
        return None

    def find_show(self, show_name: str, **kwargs: Any) -> list[UnprocessedShow]:
        return []

    def find_show_info(self, show_id: str, **kwargs: Any) -> UnprocessedShow | None:
        return None

    def get_episode_count(self, link: Link, **kwargs: Any) -> int | None:
        return None

    def get_show_score(self, show: Show, link: Link, **kwargs: Any) -> float | None:
        return None

    def get_seasonal_shows(
        self, year: int | None = None, season: str | None = None, **kwargs: Any
    ) -> list[UnprocessedShow]:
        return []
