import logging
from dataclasses import dataclass
from typing import Any

from config import Config
from data.database import DatabaseDatabase
from data.models import Episode, Poll, Show, Stream
from reddit import RedditHolo, get_shortlink_from_id
from services import AbstractPollHandler, Handlers

logger = logging.getLogger(__name__)

_MAX_LINES = 13
_MAX_COLS = 4
MAX_EPISODES = _MAX_LINES * _MAX_COLS


@dataclass
class EpisodeInfo:
    episode: Episode
    show: Show
    stream: Stream
    poll: Poll | None = None


class SubmissionBuilder:
    def __init__(
        self, db: DatabaseDatabase, config: Config, services: Handlers
    ) -> None:
        self._db = db
        self._config = config
        self._services = services
        self._data: EpisodeInfo | None = None

    @property
    def db(self) -> DatabaseDatabase:
        return self._db

    @property
    def config(self) -> Config:
        return self._config

    @property
    def services(self) -> Handlers:
        return self._services

    @property
    def poll(self) -> Poll | None:
        if not self._data:
            raise AttributeError("Missing episode information")
        return self._data.poll

    @poll.setter
    def poll(self, poll: Poll | None) -> None:
        if not self._data:
            raise AttributeError("Missing episode information")
        self._data.poll = poll

    @property
    def episode(self) -> Episode:
        if not self._data:
            raise AttributeError("Missing episode information")
        return self._data.stream.to_display_episode(self._data.episode)

    @property
    def episode_raw(self) -> Episode:
        if not self._data:
            raise AttributeError("Missing episode information")
        return self._data.episode

    @property
    def show(self) -> Show:
        if not self._data:
            raise AttributeError("Missing show information")
        return self._data.show

    @property
    def stream(self) -> Stream:
        if not self._data:
            raise AttributeError("Missing stream information")
        return self._data.stream

    def set_data(
        self, show: Show, episode: Episode, stream: Stream, raw: bool = False
    ) -> None:
        self._data = EpisodeInfo(
            episode=episode if raw else stream.to_internal_episode(episode),
            show=show,
            stream=stream,
        )

    def create_reddit_post(
        self, batch: bool = False, reddit_agent: RedditHolo | None = None
    ) -> str | None:
        title, body = self._create_submission_contents(batch=batch)
        if not reddit_agent:
            return None
        new_post = reddit_agent.submit_text_post(title, body)
        if not new_post:
            logger.error("Failed to submit post")
            return None
        logger.debug("Post successful")
        return get_shortlink_from_id(new_post.id)

    def edit_reddit_post(
        self, url: str, reddit_agent: RedditHolo | None = None
    ) -> None:
        _, body = self._create_submission_contents(quiet=True)
        if reddit_agent:
            reddit_agent.edit_text_post(url, body)

    def _create_submission_contents(
        self, batch: bool = False, quiet: bool = False
    ) -> tuple[str, str]:
        title = self._create_post_title()
        title = self.format_post_text(title)
        logger.info("Title:\n%s", title)
        body = self.format_post_text(
            self.config.batch_thread_post_body if batch else self.config.post_body
        )
        if not quiet:
            logger.info("Body:\n%s", body)
        return title, body

    def format_post_text(self, text: str) -> str:
        # TODO: change to a more block-based system (can exclude blocks without content)
        if "{spoiler}" in text:
            text = safe_format(text, spoiler=self._gen_text_spoiler())
        if "{streams}" in text:
            text = safe_format(text, streams=self._gen_text_streams())
        if "{links}" in text:
            text = safe_format(text, links=self._gen_text_links())
        if "{discussions}" in text:
            text = safe_format(text, discussions=self._gen_text_discussions())
        if "{aliases}" in text:
            text = safe_format(text, aliases=self._gen_text_aliases())
        if "{poll}" in text:
            text = safe_format(text, poll=self._gen_text_poll())

        episode_name = f": {self.episode.name}" if self.episode.name else ""
        episode_alt_number = (
            f" ({self.episode.number + self.stream.remote_offset})"
            if self.stream.remote_offset
            else ""
        )
        text = safe_format(
            text,
            show_name=self.show.name,
            show_name_en=self.show.name_en,
            episode=self.episode.number,
            episode_alt_number=episode_alt_number,
            episode_name=episode_name,
        )
        return text.strip()

    def _create_post_title(self) -> str:
        title = (
            self.config.post_title_with_en
            if self.show.name_en
            else self.config.post_title
        )
        if (
            self.episode.number == self.show.length
            and self.config.post_title_postfix_final
        ):
            title += " " + self.config.post_title_postfix_final
        return title

    def _create_megathread_title(self) -> str:
        if self.show.name_en:
            return self.config.batch_thread_post_title_with_en
        return self.config.batch_thread_post_title

    def _gen_text_spoiler(self) -> str:
        logger.debug(
            "Generating spoiler text for show %s, spoiler is %s",
            self.show,
            self.show.has_source,
        )
        if self.show.has_source:
            return self.config.post_formats["spoiler"]
        return ""

    def _gen_text_streams(self) -> str:
        logger.debug("Generating stream text for show %s", self.show)
        streams = self.db.get_streams_for_show(self.show)
        stream_texts = filter(None, map(self._gen_text_stream, streams))
        lite_streams = self.db.get_lite_streams_from_show(self.show)
        lite_stream_texts = (
            safe_format(
                self.config.post_formats["stream"],
                service_name=lite_stream.service_name,
                stream_link=lite_stream.url,
            )
            for lite_stream in lite_streams
        )
        if stream_texts or lite_stream_texts:
            return "\n".join(stream_texts) + "\n".join(lite_stream_texts)
        return "*None*"

    def _gen_text_stream(self, stream: Stream) -> str | None:
        service = self.db.get_service_from_id(stream.service)
        if not (service and service.enabled and service.use_in_post):
            return None
        stream_handler = self.services.streams.get(service.key, None)
        if not stream_handler:
            return None
        return safe_format(
            self.config.post_formats["stream"],
            service_name=service.name,
            stream_link=stream_handler.get_stream_link(stream),
        )

    def _gen_text_links(self) -> str:
        logger.debug("Generating stream text for show %s", self.show)
        links = self.db.get_links(show=self.show)
        link_texts: list[str] = []
        link_texts_bottom: list[str] = []  # for links that come last
        for link in links:
            site = self.db.get_link_site_from_id(link.site)
            if not (site and site.enabled):
                continue
            link_handler = self.services.infos.get(site.key, None)
            if not link_handler:
                continue
            if site.key == "subreddit":
                text = safe_format(
                    self.config.post_formats["link_reddit"],
                    link=link_handler.get_link(link),
                )
            else:
                text = safe_format(
                    self.config.post_formats["link"],
                    site_name=site.name,
                    link=link_handler.get_link(link),
                )
            if site.key in {"subreddit", "official"}:
                link_texts_bottom.append(text)
            else:
                link_texts.append(text)

        return "\n".join(link_texts) + "\n" + "\n".join(link_texts_bottom)

    def _gen_text_discussions(self) -> str:
        episodes = self.db.get_episodes(self.show)
        if not episodes:
            return self.config.post_formats["discussion_none"]
        logger.debug("Num previous episodes: %d", len(episodes))
        if len(episodes) > MAX_EPISODES:
            logger.debug("Clipping to most recent %d episodes", MAX_EPISODES)
            episodes = episodes[-MAX_EPISODES:]
        table = [
            self._episode_table_entry(episode=self.stream.to_display_episode(episode))
            for episode in episodes
        ]
        return _table_episode_format(
            table=table,
            header=self.config.post_formats["discussion_header"],
            align=self.config.post_formats["discussion_align"],
        )

    def _episode_table_entry(
        self, episode: Episode, poll_handler: AbstractPollHandler | None = None
    ) -> str:
        poll_handler = poll_handler or self.services.default_poll
        poll = self.db.get_poll(self.show, episode)
        poll_score, poll_link = _poll_data_str(poll, poll_handler)
        return safe_format(
            self.config.post_formats["discussion"],
            episode=episode.number,
            link=episode.link,
            score=poll_score,
            poll_link=poll_link,
        )

    def _gen_text_aliases(self) -> str:
        aliases = self.db.get_aliases(self.show)
        if not aliases:
            return ""
        return safe_format(
            string=self.config.post_formats["aliases"], aliases=", ".join(aliases)
        )

    def _get_poll(self, poll_handler: AbstractPollHandler | None = None) -> None:
        poll_handler = poll_handler or self.services.default_poll
        poll = self.db.get_poll(self.show, self.episode)
        if poll:
            self.poll = poll
            return
        if self.config.debug:
            return
        title = self.config.post_poll_title.format(
            show=self.show.name, episode=self.episode.number
        )
        poll_id = poll_handler.create_poll(
            title, headers={"User-Agent": self.config.useragent}
        )
        if not poll_id:
            return
        site = self.db.get_poll_site(key=poll_handler.key)
        self.db.add_poll(self.show, self.episode, site, poll_id)
        self.poll = self.db.get_poll(self.show, self.episode)

    def _gen_text_poll(self, poll_handler: AbstractPollHandler | None = None) -> str:
        if not self.poll:
            return ""
        poll_handler = poll_handler or self.services.default_poll
        return safe_format(
            self.config.post_formats["poll"],
            poll_url=poll_handler.get_link(self.poll),
            poll_results_url=poll_handler.get_results_link(self.poll),
        )


def _table_episode_format(table: list[str], header: str, align: str) -> str:
    num_columns = 1 + (len(table) - 1) // _MAX_LINES
    table_head = (
        "|".join(num_columns * [header]) + "\n" + "|".join(num_columns * [align])
    )
    table = ["|".join(table[i::_MAX_LINES]) for i in range(_MAX_LINES)]
    return table_head + "\n" + "\n".join(table)


def _poll_data_str(
    poll: Poll | None, poll_handler: AbstractPollHandler
) -> tuple[str, str]:
    if not poll:
        score = None
        poll_link = None
    else:
        score = poll.score or poll_handler.get_score(poll)
        poll_link = poll_handler.get_results_link(poll)
    score = poll_handler.convert_score_str(score)
    return score, poll_link or "http://localhost"


class _SafeDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def safe_format(string: str, **kwargs: Any) -> str:
    """
    A safer version of the default str.format(...) function.
    Ignores unused keyword arguments and unused '{...}' placeholders instead of throwing a KeyError.
    :param s: The string being formatted
    :param kwargs: The format replacements
    :return: A formatted string
    """
    return string.format_map(_SafeDict(**kwargs))
