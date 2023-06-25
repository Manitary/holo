from __future__ import annotations

import importlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from functools import lru_cache, wraps
from json import JSONDecodeError
from time import perf_counter, sleep
from types import ModuleType
from typing import Any, Callable, Iterable, Type, TypeVar
from xml.etree import ElementTree as xml_parser

import feedparser
import requests
from bs4 import BeautifulSoup

from config import Config
from data.models import (
    Episode,
    Link,
    LinkSite,
    Poll,
    Service,
    Show,
    Stream,
    UnprocessedShow,
    UnprocessedStream,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ServiceTypes(StrEnum):
    STREAM = "ServiceHandler"
    INFO = "InfoHandler"
    POLL = "PollHandler"


@dataclass
class Handlers:
    streams: dict[str, AbstractServiceHandler] = field(default_factory=dict)
    infos: dict[str, AbstractInfoHandler] = field(default_factory=dict)
    polls: dict[str, AbstractPollHandler] = field(default_factory=dict)

    def __init__(self, config: Config) -> None:
        for service_type in ServiceTypes:
            name = str(service_type.name).lower()
            self.__setattr__(
                f"{name}s", import_services(name, str(service_type), config)
            )


def import_services(
    package_name: str, class_name: str, config: Config
) -> dict[str, BaseHandler]:
    package = importlib.import_module(f".{package_name}", package=__name__)
    services: dict[str, BaseHandler] = {}
    for name in package.__all__:
        module = importlib.import_module(f".{name}", package=package.__name__)
        if not hasattr(module, class_name):
            logger.warning(
                "Service module %s.%s has no handler %s",
                package.__name__,
                module.__name__,
                class_name,
            )
            continue
        handler: BaseHandler = getattr(module, class_name)()
        handler.set_config(config=config.services.get(handler.key, {}))
        services[handler.key] = handler
    return services


# Common

_service_configs: dict[str, dict[str, str]] = {}


def setup_services(config: Config) -> None:
    global _service_configs
    _service_configs = config.services


def _get_service_config(key: str) -> dict[str, str]:
    return _service_configs.get(key, {})


def _make_service(service: AbstractServiceHandler) -> AbstractServiceHandler:
    service.set_config(_get_service_config(service.key))
    return service


# Utilities


def import_all_services(pkg: ModuleType, class_name: str) -> dict[str, Any]:
    services: dict[str, AbstractServiceHandler] = {}
    for name in pkg.__all__:
        module = importlib.import_module("." + name, package=pkg.__name__)
        if not hasattr(module, class_name):
            logger.warning(
                "Service module %s.%s has no handler %s", pkg.__name__, name, class_name
            )
        handler = getattr(module, class_name)()
        services[handler.key] = _make_service(handler)
        del module
    return services


##############
# Requesting #
##############


def rate_limit(wait_length: float) -> Callable[[Callable[..., T]], Callable[..., T]]:
    last_time = 0

    def decorate(f: Callable[..., T]) -> Callable[..., T]:
        @wraps(wrapped=f)
        def rate_limited(*args: Any, **kwargs: Any) -> T:
            nonlocal last_time
            diff = perf_counter() - last_time
            if diff < wait_length:
                sleep(wait_length - diff)

            r = f(*args, **kwargs)
            last_time = perf_counter()
            return r

        return rate_limited

    return decorate


class Requestable:
    rate_limit_wait = 1
    default_timeout = 10

    @lru_cache(maxsize=100)
    @rate_limit(rate_limit_wait)
    def request(
        self,
        url: str,
        proxy: tuple[str, int] | None = None,
        useragent: str = "",
        auth: tuple[str, str] | None = None,
        timeout: int = default_timeout,
    ) -> requests.Response | None:
        """
        Sends a request to the service.
        :param proxy: Optional proxy, a tuple of address and port
        :param useragent: Ideally should always be set
        :param auth: Tuple of username and password to use for HTTP basic auth
        :param timeout: Amount of time to wait for a response in seconds
        :return: The response if successful, otherwise None
        """
        proxies: dict[str, str] | None = None
        if proxy:
            try:
                proxies = {"http": f"http://{proxy[0]}:{proxy[1]}"}
                logger.debug("Using proxy: %s", proxies)
            except Exception:
                logger.warning("Invalid proxy, need address and port")

        headers = {"User-Agent": useragent}
        logger.debug("Sending request")
        logger.debug("  URL=%s", url)
        logger.debug("  Headers=%s", headers)
        try:
            response = requests.get(
                url, headers=headers, proxies=proxies, auth=auth, timeout=timeout
            )
        except requests.exceptions.Timeout:
            logger.error("  Response timed out")
            return None
        logger.debug("  Status code: %s", response.status_code)
        if (
            not response.ok or response.status_code == 204
        ):  # 204 is a special case for MAL errors
            logger.error("Response %s: %s", response.status_code, response.reason)
            return None
        if (
            not response.text
        ):  # Some sites *coughfunimationcough* may return successful empty responses for new shows
            logger.error("Empty response (probably Funimation)")
            return None

        return response

    def request_json(self, url: str, **kwargs: Any) -> Any:
        response = self.request(url=url, **kwargs)
        logger.debug("Response returning as JSON")
        if not response:
            return None
        try:
            return response.json()
        except JSONDecodeError as e:
            logger.error("Response is not JSON", exc_info=e)
            return None

    def request_xml(self, url: str, **kwargs: Any) -> xml_parser.Element | None:
        response = self.request(url=url, **kwargs)
        logger.debug("Response returning as XML")
        if not response:
            return None
        # TODO: error checking
        raw_entry = xml_parser.fromstring(response.text)
        # entry = dict((attr.tag, attr.text) for attr in raw_entry)
        return raw_entry

    def request_html(self, url: str, **kwargs: Any) -> BeautifulSoup | None:
        response = self.request(url=url, **kwargs)
        logger.debug("Returning response as HTML")
        if not response:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        return soup

    def request_rss(self, url: str, **kwargs: Any) -> feedparser.FeedParserDict | None:
        response = self.request(url=url, **kwargs)
        logger.debug("Returning response as RSS feed")
        if not response:
            return None
        rss: feedparser.FeedParserDict = feedparser.parse(response.text)
        return rss

    def request_text(self, url: str, **kwargs: Any) -> str | None:
        response = self.request(url=url, **kwargs)
        logger.debug("Response returning as text")
        if not response:
            return None
        return response.text


@dataclass(kw_only=True)
class BaseHandler:
    key: str
    config: dict[str, str] = field(default_factory=dict)

    def set_config(self, config: dict[str, str]) -> None:
        self.config = config


###################
# Service handler #
###################


class AbstractServiceHandler(BaseHandler, Requestable, ABC):
    def __init__(
        self, name: str, is_generic: int | bool, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.name = name
        self.is_generic = is_generic

    def get_latest_episode(self, stream: Stream, **kwargs: Any) -> Episode | None:
        """
        Gets information on the latest episode for this service.
        :param stream: The stream being checked
        :param kwargs: Arguments passed to the request, such as proxy and authentication
        :return: The latest episode, or None if no episodes are found and valid
        """
        episodes = self.get_published_episodes(stream, **kwargs)
        return max(episodes, key=lambda e: e.number, default=None)

    def get_published_episodes(
        self, stream: Stream, **kwargs: Any
    ) -> Iterable[Episode]:
        """
        Gets all possible live episodes for a given stream. Not all older episodes are
        guaranteed to be returned due to potential API limitations.
        :param stream: The stream being checked
        :param kwargs: Arguments passed to the request, such as proxy and authentication
        :return: An iterable of live episodes
        """
        episodes = self.get_all_episodes(stream, **kwargs)
        today = (
            datetime.utcnow().date()
        )  # NOTE: Uses local time instead of UTC, but probably doesn't matter too much on a day scale
        return filter(
            lambda e: e.date and e.date.date() <= today, episodes
        )  # Update 9/14/16: It actually matters.

    @abstractmethod
    def get_all_episodes(self, stream: Stream, **kwargs: Any) -> Iterable[Episode]:
        """
        Gets all possible episodes for a given stream. Not all older episodes are
        guaranteed to be returned due to potential API limitations.
        :param stream: The stream being checked
        :param kwargs: Arguments passed to the request, such as proxy and authentication
        :return: A list of live episodes
        """
        return []

    def get_recent_episodes(
        self, streams: Iterable[Stream], **kwargs: Any
    ) -> dict[Stream, list[Episode]]:
        """
        Gets all recently released episode on the service, for the given streams.
        What counts as recent is decided by the service handler, but all newly released episodes
        should be returned by this function.
        By default, calls get_all_episodes for each stream.
        :param streams: The streams for which new episodes must be returned.
        :param kwargs: Arguments passed to the request, such as proxy and authentication
        :return: A dict in which each key is one of the requested streams
                 and the value is a list of newly released episodes for the stream
        """
        return {
            stream: list(self.get_all_episodes(stream, **kwargs)) for stream in streams
        }

    @abstractmethod
    def get_stream_link(self, stream: Stream) -> str | None:
        """
        Creates a URL to a show's main stream page hosted by this service.
        :param stream: The show's stream
        :return: A URL to the stream's page
        """
        return None

    @abstractmethod
    def extract_show_key(self, url: str) -> str | None:
        """
        Extracts a show's key from its URL.
        For example, "myriad-colors-phantom-world" is extracted from the Crunchyroll URL
                http://www.crunchyroll.com/myriad-colors-phantom-world.rss
        :param url:
        :return: The show's service key
        """
        return None

    @abstractmethod
    def get_stream_info(self, stream: Stream, **kwargs: Any) -> Stream | None:
        """
        Get information about the stream, including name and ID.
        :param stream: The stream being checked
        :return: An updated stream object if successful, otherwise None"""
        return None

    @abstractmethod
    def get_seasonal_streams(self, **kwargs: Any) -> list[UnprocessedStream]:
        """
        Gets a list of streams for the current or nearly upcoming season.
        :param kwargs: Extra arguments, particularly useragent
        :return: A list of UnprocessedStreams (empty list if no shows or error)
        """
        return []


# Services

_services: dict[str, AbstractServiceHandler] = {}


def _ensure_service_handlers() -> None:
    global _services
    if not _services:
        from . import stream

        _services = import_all_services(stream, "ServiceHandler")


def get_service_handlers() -> dict[str, AbstractServiceHandler]:
    """
    Creates an instance of every service in the services module and returns a mapping to their keys.
    :return: A dict of service keys to an instance of the service
    """
    _ensure_service_handlers()
    return _services


def get_service_handler(
    service: Service | None = None, key: str | None = None
) -> AbstractServiceHandler | None:
    """
    Returns an instance of a service handler representing the given service or service key.
    :param service: A service
    :param key: A service key
    :return: A service handler instance
    """
    _ensure_service_handlers()
    if service and service.key in _services:
        return _services[service.key]
    if key and key in _services:
        return _services[key]
    return None


@lru_cache(maxsize=1)
def get_generic_service_handlers(
    services: Iterable[AbstractServiceHandler] | None = None,
    keys: Iterable[str] | None = None,
) -> list[AbstractServiceHandler]:
    _ensure_service_handlers()
    if services and not keys:
        keys = {s.key for s in services}
    return [
        service
        for key, service in _services.items()
        if (not keys or key in keys) and service.is_generic
    ]


################
# Link handler #
################


class AbstractInfoHandler(BaseHandler, Requestable, ABC):
    def __init__(self, name: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.name = name
        self.config: dict[str, str] = {}

    @abstractmethod
    def get_link(self, link: Link) -> str | None:
        """
        Creates a URL using the information provided by a link object.
        :param link: The link object
        :return: A URL
        """
        return None

    @abstractmethod
    def extract_show_id(self, url: str) -> str | None:
        """
        Extracts a show's ID from its URL.
        For example, 31737 is extracted from the MAL URL
                http://myanimelist.net/anime/31737/Gakusen_Toshi_Asterisk_2nd_Season
        :param url:
        :return: The show's service ID
        """
        return None

    @abstractmethod
    def find_show(self, show_name: str, **kwargs: Any) -> list[UnprocessedShow]:
        """
        Searches the link site for a show with the specified name.
        :param show_name: The desired show's name
        :param kwargs: Extra arguments, particularly useragent
        :return: A list of shows (empty list if no shows or error)
        """
        return []

    @abstractmethod
    def find_show_info(self, show_id: str, **kwargs: Any) -> UnprocessedShow | None:
        return None

    @abstractmethod
    def get_episode_count(self, link: Link, **kwargs: Any) -> int | None:
        """
        Gets the episode count of the specified show on the site given by the link.
        :param link: The link pointing to the site being checked
        :param kwargs: Extra arguments, particularly useragent
        :return: The episode count, otherwise None
        """
        return None

    @abstractmethod
    def get_show_score(self, show: Show, link: Link, **kwargs: Any) -> float | None:
        """
        Gets the score of the specified show on the site given by the link.
        :param show: The show being checked
        :param link: The link pointing to the site being checked
        :param kwargs: Extra arguments, particularly useragent
        :return: The show's score, otherwise None
        """
        return None

    @abstractmethod
    def get_seasonal_shows(
        self, year: int | None = None, season: str | None = None, **kwargs: Any
    ) -> list[UnprocessedShow]:
        """
        Gets a list of shows airing in a particular season.
        If year and season are None, uses the current season.
        Note: Not all sites may allow specific years and seasons.
        :param year:
        :param season:
        :param kwargs: Extra arguments, particularly useragent
        :return: A list of UnprocessedShows (empty list if no shows or error)
        """
        return []


# Link sites

_link_sites: dict[str, AbstractInfoHandler] = {}


def _ensure_link_handlers() -> None:
    global _link_sites
    if not _link_sites:
        from . import info

        _link_sites = import_all_services(info, "InfoHandler")


def get_link_handlers() -> dict[str, AbstractInfoHandler]:
    """
    Creates an instance of every link handler in the links module and returns a mapping to their keys.
    :return: A dict of link handler keys to an instance of the link handler
    """
    _ensure_link_handlers()
    return _link_sites


def get_link_handler(
    link_site: LinkSite | None = None, key: str | None = None
) -> AbstractInfoHandler | None:
    """
    Returns an instance of a link handler representing the given link site.
    :param link_site: A link site
    :param key: A link site key
    :return: A link handler instance
    """
    _ensure_link_handlers()
    if link_site and link_site.key in _link_sites:
        return _link_sites[link_site.key]
    if key and key in _link_sites:
        return _link_sites[key]
    return None


################
# Poll handler #
################


class AbstractPollHandler(BaseHandler, Requestable, ABC):
    @abstractmethod
    def create_poll(self, title: str, submit: bool, **kwargs: Any) -> str | None:
        """
        Create a new Poll.
        :param title: title of this poll
        :return: the id of the poll
        """
        return None

    @abstractmethod
    def get_link(self, poll: Poll) -> str | None:
        """
        Creates a URL using the information provided by the poll object.
        :param poll: the Poll object
        :return: a URL
        """
        return None

    @abstractmethod
    def get_results_link(self, poll: Poll) -> str | None:
        """
        Creates a URL for the poll results using the information provided by the poll object.
        :param poll: the Poll object
        :return: a URL
        """
        return None

    @abstractmethod
    def get_score(self, poll: Poll) -> float | None:
        """
        Return the score of this poll.
        :param poll: the Poll object
        :return: the score on a 1-10 scale
        """
        return None

    @staticmethod
    def convert_score_str(score: float | None) -> str:
        if score:
            return str(score)
        return "----"


_poll_sites: dict[str, AbstractPollHandler] = {}


def _ensure_poll_handlers() -> None:
    global _poll_sites
    if not _poll_sites:
        from . import poll

        _poll_sites = import_all_services(poll, "PollHandler")


def get_poll_handlers() -> dict[str, AbstractPollHandler]:
    """
    Creates an instance of every poll handler in the polls module and returns a mapping to their keys.
    :return: a dict of poll handler keys to the instance of th poll handler
    """
    _ensure_poll_handlers()
    return _poll_sites


def get_default_poll_handler() -> AbstractPollHandler:
    """
    Returns an instance of the default poll handler.
    :return: the handler
    """
    _ensure_poll_handlers()
    return _poll_sites["youpoll"]
