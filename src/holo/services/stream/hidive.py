import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag

from ...data.models import Episode, Stream, UnprocessedStream
from .. import AbstractServiceHandler

logger = logging.getLogger(__name__)


class ServiceHandler(AbstractServiceHandler):
    _show_url = "https://www.hidive.com/season/{id}"
    _show_re = re.compile(r"hidive.com/season/(\d+)", re.I)
    _date_re = re.compile(r"Premiere: (\d+)/(\d+)/(\d+)")

    def __init__(self) -> None:
        super().__init__(key="hidive", name="HIDIVE", is_generic=False)

    # Episode finding

    def get_all_episodes(self, stream: Stream, **kwargs: Any) -> list[Episode]:
        logger.info("Getting live episodes for HiDive/%s", stream.show_key)

        episode_datas = self._get_feed_episodes(stream.show_key, **kwargs)

        # HIDIVE does not include episode date in the show's page
        # Pre-process the data to obtain all the other information
        # Sort the episodes by descending number
        # Stop at the first invalid episode
        # (Assumption: all new episodes have increasing numbers)
        # This is to reduce the number of requests to make
        episodes_candidates = sorted(
            list(filter(None, map(_preprocess_episode, episode_datas))),
            key=lambda e: e.number,
            reverse=True,
        )

        episodes: list[Episode] = []
        for episode in episodes_candidates:
            try:
                if episode := self.validate_episode(
                    episode=episode, show_key=stream.show_key, **kwargs
                ):
                    episodes.append(episode)
                else:
                    break
            except Exception:
                logger.exception(
                    "Problem digesting episode for HiDive/%s: %s",
                    stream.show_key,
                    episode.link,
                )
        logger.debug("  %d episodes found, %d valid", len(episode_datas), len(episodes))
        return episodes

    def _get_feed_episodes(self, show_key: str, **kwargs: Any) -> list[dict[str, Any]]:
        logger.info("Getting episodes for HiDive/%s", show_key)

        data = _load_real_page(show_key)
        if not data:
            logger.error("Cannot get show page for HiDive/%s", show_key)
            return []

        episodes = data["elements"][2]["attributes"]["items"]
        return episodes

    @classmethod
    def _get_feed_url(cls, show_key: str) -> str:
        if show_key:
            return cls._show_url.format(id=show_key)
        return ""

    # Remove info getting

    def get_stream_info(self, stream: Stream, **kwargs: Any) -> Stream | None:
        logger.info("Getting stream info for HiDive/%s", stream.show_key)

        url = self._get_feed_url(stream.show_key)
        if not url:
            logger.error("Cannot get url from show key")
            return None

        real_page = _load_real_page(stream.show_key)
        if not real_page:
            logger.error("Cannot get feed")
            return None

        try:
            title = real_page["elements"][0]["attributes"]["header"]["attributes"][
                "text"
            ]
        except (KeyError, IndexError):
            logger.error("Could not extract title")
            return None
        stream.name = title
        return stream

    def get_seasonal_streams(self, **kwargs: Any) -> list[UnprocessedStream]:
        # What is this for again ?
        return []

    def get_stream_link(self, stream: Stream) -> str:
        return self._show_url.format(id=stream.show_key)

    def extract_show_key(self, url: str) -> str | None:
        if match := self._show_re.search(url):
            return match.group(1)
        return None

    def validate_episode(
        self, episode: Episode, show_key: str, **kwargs: Any
    ) -> Episode | None:
        episode_id = re.match(
            r"https://www.hidive.com/interstitial/(\d+)", episode.link
        )
        if not episode_id:
            logger.error("Invalid ep id parsing")
            return None
        data = _load_episode_page(episode_id.group(1))
        if not data:
            logger.error("Invalid episode link for show %s/%s", self.key, show_key)
            return None

        content = data["elements"][0]["attributes"]["content"]
        content_elt = next((c for c in content if c["$type"] == "tagList"))
        tags = content_elt["attributes"]["tags"]
        date_tag = next(
            (t for t in tags if t["attributes"]["text"].startswith("Original Premiere"))
        )
        date_data = date_tag["attributes"]["text"]
        date_text = re.match(r"Original Premiere: (.*)", date_data)
        if not date_text:
            logger.error("Invalid date text: %s", date_data)
            return episode
        date = datetime.strptime(date_text.group(1), "%B %d, %Y")

        # HIDIVE only has m/d/y, not hh:mm
        episode_day = datetime(day=date.day, month=date.month, year=date.year)
        date_diff = datetime.now(UTC).replace(tzinfo=None) - episode_day
        if date_diff >= timedelta(days=2):
            logger.debug("  Episode too old")
            return None
        episode.date = episode_day
        return episode


def _preprocess_episode(feed_episode: dict[str, Any]) -> Episode | None:
    logger.debug("Pre-processing episode")

    episode_link = f"https://www.hidive.com/interstitial/{feed_episode['id']}"

    title_match = re.match(r"E(\d+)(?:\.00)? - (.*)", feed_episode["title"])
    if not title_match:
        logger.warning("Unknown episode number format in %s", episode_link)
        return None

    num, name = title_match.groups()
    num = int(num)
    if num == 0:
        logger.warning("Excluding episode numbered 0: %s", episode_link)
        return None
    unreleased = re.match(r"Coming \d+/\d+/\d+ .*", name)
    if unreleased:
        logger.debug("Excluding unreleased episode: %s", episode_link)
        return None

    date = datetime.now(UTC).replace(tzinfo=None)  # Not included in stream !

    return Episode(number=num, name=name, link=episode_link, date=date)


def _load_real_page(show_id: int | str):
    base_url = f"https://www.hidive.com/season/{show_id}"
    r = requests.get(base_url, timeout=60)
    if not r.ok:
        logger.error("Couldn't fetch show landing page. Status code: %s", r.status_code)
        return
    json_path = re.findall(r"src=\"(.*?/\d+\.js)\"", r.text)[-1]
    js_url = f"https://www.hidive.com{json_path}"
    r2 = requests.get(js_url, timeout=60)
    api_key = re.findall(r"API_KEY:\"(.*?)\"", r2.text)[0]
    auth_url = "https://dce-frontoffice.imggaming.com/api/v1/init/?lk=language&pk=subTitleLanguage&pk=audioLanguage&pk=autoAdvance&pk=pluginAccessTokens&readLicences=true"
    r3 = requests.get(
        auth_url,
        headers={"Origin": "https://www.hidive.com", "X-Api-Key": api_key},
        timeout=60,
    )
    auth_token = re.findall(r"authorisationToken\":\"(.*?)\"", r3.text)[0]
    true_url = (
        f"https://dce-frontoffice.imggaming.com/api/v1/view?type=season&id={show_id}"
    )
    r4 = requests.get(
        true_url,
        headers={
            "Realm": "dce.hidive",
            "Authorization": f"Bearer {auth_token}",
            "X-Api-Key": api_key,
        },
        timeout=60,
    )
    true_page = r4.text
    j = json.loads(true_page)
    return j


def _load_episode_page(episode_id: int | str):
    base_url = f"https://www.hidive.com/interstitial/{episode_id}"
    r = requests.get(base_url, timeout=60)
    if not r.ok:
        logger.error(
            "Couldn't fetch episode landing page. Status code: %s", r.status_code
        )
        return
    json_path = re.findall(r"src=\"(.*?/\d+\.js)\"", r.text)[-1]
    js_url = f"https://www.hidive.com{json_path}"
    r2 = requests.get(js_url, timeout=60)
    api_key = re.findall(r"API_KEY:\"(.*?)\"", r2.text)[0]
    auth_url = "https://dce-frontoffice.imggaming.com/api/v1/init/?lk=language&pk=subTitleLanguage&pk=audioLanguage&pk=autoAdvance&pk=pluginAccessTokens&readLicences=true"
    r3 = requests.get(
        auth_url,
        headers={"Origin": "https://www.hidive.com", "X-Api-Key": api_key},
        timeout=60,
    )
    auth_token = re.findall(r"authorisationToken\":\"(.*?)\"", r3.text)[0]
    true_url = (
        f"https://dce-frontoffice.imggaming.com/api/v1/view?type=VOD&id={episode_id}"
    )
    r4 = requests.get(
        true_url,
        headers={
            "Realm": "dce.hidive",
            "Authorization": f"Bearer {auth_token}",
            "X-Api-Key": api_key,
        },
        timeout=60,
    )
    true_page = r4.text
    j = json.loads(true_page)
    return j
