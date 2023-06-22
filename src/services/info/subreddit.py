# Dummy info handler, used for official website of shows

import logging
import re
from typing import Any

from data.models import Link

from .. import AbstractInfoHandler

logger = logging.getLogger(__name__)


class InfoHandler(AbstractInfoHandler):
    _show_link_base = "/r/{id}"
    _show_link_matcher = r"/r/(\w+)"

    def __init__(self) -> None:
        super().__init__("subreddit", "/r/")

    def get_link(self, link: Link | None) -> str | None:
        if link is None:
            return None
        return self._show_link_base.format(id=link.site_key)

    def extract_show_id(self, url: str | None) -> str | None:
        if url is not None:
            match = re.search(self._show_link_matcher, url, re.I)
            if match:
                return match.group(1)
        return None

    def find_show(self, show_name: str, **kwargs: Any):
        return list()

    def find_show_info(self, show_id, **kwargs):
        return None

    def get_episode_count(self, link, **kwargs):
        return None

    def get_show_score(self, show, link, **kwargs):
        return None

    def get_seasonal_shows(self, year=None, season=None, **kwargs):
        return list()
