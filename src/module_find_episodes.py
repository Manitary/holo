import logging
from typing import Generator, Iterable

from config import Config
from data.database import DatabaseDatabase
from data.models import Episode, Show, Stream
from reddit import RedditHolo
from services import AbstractServiceHandler, Handlers
from submission import SubmissionBuilder, MAX_EPISODES

logger = logging.getLogger(__name__)


def main(config: Config, db: DatabaseDatabase, handlers: Handlers) -> None:
    reddit_holo = RedditHolo(config=config)
    submitter = SubmissionBuilder(db=db, config=config, services=handlers)

    enabled_services = db.get_services(enabled=True)
    has_new_episode: list[tuple[Show, Episode]] = []

    # Check services for new episodes
    for service in enabled_services:
        service_handler = handlers.streams.get(service.key, None)
        if not service_handler:
            continue

        streams = db.get_streams_for_service(service=service)
        logger.debug("%d streams found", len(streams))

        for show, episode in _process_service_streams(
            stream_handler=service_handler,
            submitter=submitter,
            reddit_agent=reddit_holo,
            streams=streams,
        ):
            has_new_episode.append((show, episode))

    other_shows = set(db.get_shows_by_enabled_status(enabled=True)) | set(
        db.get_shows_delayed()
    )
    if len(other_shows) > 0:
        logger.info("Checking generic services for %d shows", len(other_shows))

    other_streams = [Stream.from_show(show) for show in other_shows]
    for service in enabled_services:
        service_handler = handlers.streams.get(service.key, None)
        if not (service_handler and service_handler.is_generic):
            continue
        logger.debug("    Checking service %s", service_handler.name)

        for show, episode in _process_service_streams(
            stream_handler=service_handler,
            submitter=submitter,
            reddit_agent=reddit_holo,
            streams=other_streams,
        ):
            has_new_episode.append((show, episode))

    logger.debug("")
    logger.debug("Summary of shows with new episodes:")
    for show, episode in has_new_episode:
        logger.debug("  %s: ep%s", show.name, episode.number)
    logger.debug("")


def _process_service_streams(
    stream_handler: AbstractServiceHandler,
    submitter: SubmissionBuilder,
    reddit_agent: RedditHolo,
    streams: Iterable[Stream],
) -> Generator[tuple[Show, Episode], None, None]:
    recent_episodes = stream_handler.get_recent_episodes(
        streams, useragent=submitter.config.useragent
    )
    logger.info(
        "%d episodes for active shows on %s %s",
        sum(map(len, recent_episodes.values())),
        "generic service" if stream_handler.is_generic else "service",
        stream_handler.name,
    )

    for stream, episodes in recent_episodes.items():
        show = submitter.db.get_show(stream)
        if not (show and show.enabled):
            continue

        logger.info('Checking stream "%s"', stream.show_key)
        logger.debug(stream)

        if not episodes:
            logger.info("  No episode found")
            continue

        for episode in sorted(episodes, key=lambda e: e.number):
            submitter.set_data(show=show, episode=episode, stream=stream)
            if _process_new_episode(submitter, reddit_agent):
                yield show, episode


def _process_new_episode(
    handler: SubmissionBuilder,
    reddit_agent: RedditHolo,
) -> bool:
    logger.debug("Processing new episode")
    logger.debug("%s", handler.episode_raw)
    logger.debug("  Date: %s", handler.episode.date)
    logger.debug("  Is live: %s", handler.episode.is_live)
    if not handler.episode.is_live:
        logger.info("  Episode not live")
        return False

    # Adjust episode to internal numbering
    logger.debug("  Adjusted num: %d", handler.episode.number)
    if handler.episode.number <= 0:
        logger.error("Episode number must be positive")
        return False

    # Check if already in database
    latest_episode = handler.db.get_latest_episode(handler.show)
    already_seen = latest_episode and latest_episode.number >= handler.episode.number
    episode_number_gap = (
        latest_episode and handler.episode.number - 1 > latest_episode.number > 0
    )
    logger.debug(
        "  Latest ep num: %s", latest_episode.number if latest_episode else "none"
    )
    logger.debug("  Already seen: %s", already_seen)
    logger.debug("  Gap between episodes: %d", episode_number_gap)

    logger.info(
        "  Posted on %s, number %d, %s, %s",
        handler.episode.date,
        handler.episode.number,
        "already seen" if already_seen else "new",
        "gap between episodes" if episode_number_gap else "expected number",
    )
    if already_seen or episode_number_gap:
        return False
    # New episode!
    post_url = handler.create_reddit_post(
        reddit_agent=None if handler.config.debug else reddit_agent,
    )
    if not post_url:
        logger.error("  Episode not submitted")
        return True
    post_url = post_url.replace("http:", "https:")
    logger.info("  Post URL: %s", post_url)
    handler.db.add_episode(handler.show, handler.episode.number, post_url)
    if handler.show.delayed:
        handler.db.set_show_delayed(handler.show, False)
    # Edit the links in previous episodes
    editing_episodes = handler.db.get_episodes(handler.show)
    if not editing_episodes:
        return True
    editing_episodes.sort(key=lambda e: e.number)
    for editing_episode in editing_episodes[-MAX_EPISODES // 2 :]:
        handler.edit_reddit_post(
            url=editing_episode.link or "",
            reddit_agent=None if handler.config.debug else reddit_agent,
        )
    return True
