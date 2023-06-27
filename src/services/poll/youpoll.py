import logging
import re
from typing import Any
from bs4 import Tag

import requests

from data.models import Poll

from .. import AbstractPollHandler

logger = logging.getLogger(__name__)


class PollHandler(AbstractPollHandler):
    OPTIONS = ["Excellent", "Great", "Good", "Mediocre", "Bad"]

    _poll_post_url = "https://youpoll.me"
    _poll_post_headers = {"User-Agent": None}
    _poll_post_data = {
        "address": "",
        "poll-1[question]": None,
        "poll-1[option1]": OPTIONS[0],
        "poll-1[option2]": OPTIONS[1],
        "poll-1[option3]": OPTIONS[2],
        "poll-1[option4]": OPTIONS[3],
        "poll-1[option5]": OPTIONS[4],
        "poll-1[min]": "1",
        "poll-1[max]": 10,
        "poll-1[voting-system]": "0",
        "poll-1[approval-validation-type]": "0",
        "poll-1[approval-validation-value]": "1",
        "poll-1[basic]": "",
        "voting-limits-dropdown": "3",
        "captcha-test-checkbox": "on",
        "reddit-link-karma": "0",
        "reddit-comment-karma": "200",
        "reddit-days-old": "0",
        "responses-input": "",
    }

    _poll_id_re = re.compile(r"youpoll.me/(\d+)", re.I)
    _poll_link = "https://youpoll.me/{id}/"
    _poll_results_link = "https://youpoll.me/{id}/r"

    def __init__(self) -> None:
        super().__init__(key="youpoll")

    def create_poll(
        self, title: str, submit: bool = False, **kwargs: Any
    ) -> str | None:
        if not submit:
            return None
        # headers = _poll_post_headers
        # headers['User-Agent'] = config.useragent
        data = self._poll_post_data
        data["poll-1[question]"] = title
        # resp = requests.post(_poll_post_url, data = data, headers = headers, **kwargs)
        try:
            resp = requests.post(
                self._poll_post_url, data=data, timeout=self.default_timeout, **kwargs
            )
        except Exception as e:
            logger.error("Could not create poll (exception in POST): %s", e)
            return None

        if not resp.ok:
            logger.error("Could not create poll (resp !OK)")
            return None
        if match := self._poll_id_re.search(resp.url):
            return match.group(1)
        logger.warning("Could not create poll (ID not found)")
        return None

    def get_link(self, poll: Poll) -> str:
        return self._poll_link.format(id=poll.id)

    def get_results_link(self, poll: Poll) -> str:
        return self._poll_results_link.format(id=poll.id)

    def get_score(self, poll: Poll) -> float | None:
        logger.debug(
            "Getting score for show %s / episode %d", poll.show_id, poll.episode
        )
        try:
            response = self.request_html(self.get_results_link(poll))
        except Exception:
            logger.error(
                "Couldn't get scores for poll %s (query error)",
                self.get_results_link(poll),
            )
            return None
        if not response:
            logger.error(
                "Couldn't get scores for poll %s (GET request failed)",
                self.get_results_link(poll),
            )
            return None
        try:
            # 5 points scale
            divs = response.find_all("div", class_="basic-option-wrapper")
            num_votes_tag = response.find("span", class_="admin-total-votes")
            if not isinstance(num_votes_tag, Tag):
                raise AttributeError
            num_votes = int(num_votes_tag.text.replace(",", ""))
            if num_votes == 0:
                logger.warning("No vote recorded, no score returned")
                return None
            values: dict[str, float] = {}
            for div in divs:
                label: str = div.find("span", class_="basic-option-title").text
                if label not in self.OPTIONS:
                    logger.error("Found unexpected label %s, aborted", label)
                    return None
                value_text: str = div.find("span", class_="basic-option-percent").text
                score = float(value_text.strip("%")) / 100
                values[label] = score
            results = [values[k] for k in self.OPTIONS]
            logger.info("Results: %s", results)
            total = round(sum(r * (5 - i) for i, r in enumerate(results)), 2)
            return total
        except Exception:
            logger.error(
                "Couldn't get scores for poll %s (parsing error)",
                self.get_results_link(poll),
            )
            return None
