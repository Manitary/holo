import logging
from datetime import datetime, timedelta

import services
from config import Config
from data.database import DatabaseDatabase

logger = logging.getLogger(__name__)


def main(config: Config, db: DatabaseDatabase) -> None:
    # Find data not provided by the edit module
    _check_missing_stream_info(config, db, update_db=not config.debug)
    # Check for new show scores
    if config.record_scores:
        _check_new_episode_scores(config, db, update_db=not config.debug)
    # Record poll scores to avoid querying them every time
    _record_poll_scores(db, update_db=not config.debug)
    # Show lengths aren't always known at the start of the season
    _check_show_lengths(config, db, update_db=not config.debug)
    # Check if shows have finished and disable them if they have
    _disable_finished_shows(db, update_db=not config.debug)


def _check_show_lengths(
    config: Config, db: DatabaseDatabase, update_db: bool = True
) -> None:
    logger.info("Checking show lengths")

    shows = db.get_shows_missing_length()
    for show in shows:
        logger.info("Updating episode count of %s (%s)", show.name, show.id)
        length = None

        # Check all info handlers for an episode count
        # Some may not implement get_episode_count and return None
        for handler in services.get_link_handlers().values():
            logger.info("  Checking %s (%s)", handler.name, handler.key)

            # Get show link to site represented by the handler
            site = db.get_link_site_from_key(key=handler.key)
            link = db.get_link(show, site)
            if not link:
                logger.error("Failed to create link")
                continue

            # Validate length
            new_length = handler.get_episode_count(link, useragent=config.useragent)
            if not new_length:
                continue
            logger.debug("    Lists length: %s", new_length)
            if length and new_length != length:
                logger.warning(
                    "    Conflict between lengths %s and %s", new_length, length
                )
            length = new_length

        # Length found, update database
        if length:
            logger.info("New episode count: %s", length)
            if update_db:
                db.set_show_episode_count(show, length)
            else:
                logger.warning("Debug enabled, not updating database")


def _disable_finished_shows(db: DatabaseDatabase, update_db: bool = True) -> None:
    logger.info("Checking for disabled shows")

    shows = db.get_shows_by_enabled_status(enabled=True)
    for show in shows:
        latest_episode = db.get_latest_episode(show)
        if latest_episode and 0 < show.length <= latest_episode.number:
            logger.info('  Disabling show "%s"', show.name)
            if latest_episode.number > show.length:
                logger.warning(
                    "    Episode number (%d) greater than show length (%d)",
                    latest_episode.number,
                    show.length,
                )
            if update_db:
                db.set_show_enabled(show, enabled=False, commit=False)
    if update_db:
        db.commit()


def _check_missing_stream_info(
    config: Config, db: DatabaseDatabase, update_db: bool = True
) -> None:
    logger.info("Checking for missing stream info")

    streams = db.get_streams_missing_name()
    for stream in streams:
        service_info = db.get_service_from_id(id=stream.service)
        if not service_info:
            continue
        logger.info(
            "Updating missing stream info of %s (%s/%s)",
            stream.name,
            service_info.name,
            stream.show_key,
        )

        service = services.get_service_handler(key=service_info.key)
        if not service:
            continue
        stream = service.get_stream_info(stream, useragent=config.useragent)
        if not stream:
            logger.error("  Stream info not found")
            continue

        logger.debug("  name=%s", stream.name)
        logger.debug("  key=%s", stream.show_key)
        logger.debug("  id=%s", stream.show_id)
        if update_db:
            db.update_stream(
                stream,
                name=stream.name,
                show_id=stream.show_id,
                show_key=stream.show_key,
                commit=False,
            )

    if update_db:
        db.commit()


def _check_new_episode_scores(
    config: Config, db: DatabaseDatabase, update_db: bool = True
) -> None:
    logger.info("Checking for new episode scores")

    shows = db.get_shows_by_enabled_status(enabled=True)
    for show in shows:
        latest_episode = db.get_latest_episode(show)
        if not latest_episode:
            continue
        logger.info(
            "For show %s (%s), episode %d",
            show.name,
            show.id,
            latest_episode.number,
        )

        scores = db.get_episode_scores(show, latest_episode)
        # Check if any scores have been found rather than checking for each service
        if scores:
            logger.info("  Already has scores, ignoring")
            continue

        for handler in services.get_link_handlers().values():
            logger.info("  Checking %s (%s)", handler.name, handler.key)

            # Get show link to site represented by the handler
            site = db.get_link_site_from_key(key=handler.key)
            link = db.get_link(show, site)
            if not link:
                logger.error("Failed to create link")
                continue

            new_score = handler.get_show_score(show, link, useragent=config.useragent)
            if new_score:
                logger.info("    Score: %f", new_score)
                db.add_episode_score(
                    show, latest_episode, site, new_score, commit=False
                )

        if update_db:
            db.commit()


def _record_poll_scores(db: DatabaseDatabase, update_db: bool = True) -> None:
    polls = db.get_polls_missing_score()
    handler = services.get_default_poll_handler()
    logger.info("Record scores for service %s", handler.key)

    updated = 0
    for poll in polls:
        if timedelta(days=8) < datetime.now() - poll.date < timedelta(days=93):
            score = handler.get_score(poll)
            logger.info(
                "Updating poll score for show %s / episode %d (%f)",
                poll.show_id,
                poll.episode,
                score,
            )
            if score:
                db.update_poll_score(poll, score, commit=update_db)
                updated += 1

    logger.info(
        "%d scores recorded, %d scores not updated", updated, len(polls) - updated
    )
