import logging
from typing import Any

import services
from config import Config
from data.database import DatabaseDatabase
from data.models import Episode, Show, Stream
from reddit import RedditHolo, get_shortlink_from_id

logger = logging.getLogger(__name__)


def main(config: Config, db: DatabaseDatabase) -> None:
    reddit_holo = RedditHolo(config=config)

    has_new_episode: list[Show] = []

    # Check services for new episodes
    enabled_services = db.get_services(enabled=True)

    for service in enabled_services:
        try:
            service_handler = services.get_service_handler(service)
            if not service_handler:
                continue

            streams = db.get_streams(service=service)
            logger.debug("%d streams found", len(streams))

            recent_episodes = service_handler.get_recent_episodes(
                streams, useragent=config.useragent
            )
            logger.info(
                "%d episodes for active shows on service %s",
                len(recent_episodes),
                service,
            )

            for stream, episodes in recent_episodes.items():
                show = db.get_show(stream=stream)
                if not show or not show.enabled:
                    continue

                logger.info('Checking stream "%s"', stream.show_key)
                logger.debug(stream)

                if not episodes:
                    logger.info("  Show/episode not found")
                    continue

                for episode in sorted(episodes, key=lambda e: e.number):
                    if _process_new_episode(
                        config, db, show, stream, episode, reddit_agent=reddit_holo
                    ):
                        has_new_episode.append(show)
        except IOError:
            logger.error("Error while getting shows on service %s", service)

    # Check generic services
    # Note : selecting only shows with missing streams avoids troll torrents,
    # but also can cause delays if supported services are later than unsupported ones
    # other_shows = set(db.get_shows(missing_stream=True)) | set(db.get_shows(delayed=True))
    other_shows = set(db.get_shows(missing_stream=False)) | set(
        db.get_shows(delayed=True)
    )
    if len(other_shows) > 0:
        logger.info("Checking generic services for %d shows", len(other_shows))

    other_streams = [Stream.from_show(show) for show in other_shows]
    for service in enabled_services:
        try:
            service_handler = services.get_service_handler(service)
            if not service_handler or not service_handler.is_generic:
                continue
            logger.debug("    Checking service %s", service_handler.name)
            recent_episodes = service_handler.get_recent_episodes(
                other_streams, useragent=config.useragent
            )
            logger.info(
                "%d episodes for active shows on generic service %s",
                len(recent_episodes),
                service,
            )

            for stream, episodes in recent_episodes.items():
                show = db.get_show(stream=stream)
                if not show or not show.enabled:
                    continue

                logger.info('Checking stream "%s"', stream.show_key)
                logger.debug(stream)

                if not episodes:
                    logger.info("  No episode found")
                    continue

                for episode in sorted(episodes, key=lambda e: e.number):
                    if _process_new_episode(
                        config, db, show, stream, episode, reddit_holo
                    ):
                        has_new_episode.append(show)
        except IOError:
            logger.error("Error while getting shows on service %s", service)

    logger.debug("")
    logger.debug("Summary of shows with new episodes:")
    for show in has_new_episode:
        logger.debug("  %s", show.name)
    logger.debug("")


# yesterday = date.today() - timedelta(days=1)


def _process_new_episode(
    config: Config,
    db: DatabaseDatabase,
    show: Show,
    stream: Stream,
    episode: Episode,
    reddit_agent: RedditHolo,
) -> bool:
    logger.debug("Processing new episode")
    logger.debug("%s", episode)
    logger.debug("  Date: %s", episode.date)
    logger.debug("  Is live: %s", episode.is_live)
    # if episode.is_live and (episode.date is None or episode.date.date() > yesterday):
    if not episode.is_live:
        logger.info("  Episode not live")
        return False

    # Adjust episode to internal numbering
    int_episode = stream.to_internal_episode(episode)
    logger.debug("  Adjusted num: %d", int_episode.number)
    if int_episode.number <= 0:
        logger.error("Episode number must be positive")
        return False

    # Check if already in database
    # already_seen = db.stream_has_episode(stream, episode.number)
    latest_episode = db.get_latest_episode(show)
    already_seen = (
        latest_episode is not None and latest_episode.number >= int_episode.number
    )
    episode_number_gap = (
        latest_episode is not None
        and latest_episode.number > 0
        and int_episode.number > latest_episode.number + 1
    )
    logger.debug(
        "  Latest ep num: %s",
        "none" if latest_episode is None else latest_episode.number,
    )
    logger.debug("  Already seen: %s", already_seen)
    logger.debug("  Gap between episodes: %d", episode_number_gap)

    logger.info(
        "  Posted on %s, number %d, %s, %s",
        episode.date,
        int_episode.number,
        "already seen" if already_seen else "new",
        "gap between episodes" if episode_number_gap else "expected number",
    )
    # New episode!
    if already_seen or episode_number_gap:
        return False
    post_url = create_reddit_post(
        config,
        db,
        show,
        stream,
        int_episode,
        reddit_agent=None if config.debug else reddit_agent,
    )
    logger.info("  Post URL: %s", post_url)
    if not post_url:
        logger.error("  Episode not submitted")
        return True

    post_url = post_url.replace("http:", "https:")
    db.add_episode(stream.show, int_episode.number, post_url)
    if show.delayed:
        db.set_show_delayed(show, False)
    # Edit the links in previous episodes
    editing_episodes = db.get_episodes(show)
    if not editing_episodes:
        return True
    edit_history_length = int(4 * 13 / 2)  # cols x rows / 2
    editing_episodes.sort(key=lambda x: x.number)
    for editing_episode in editing_episodes[-edit_history_length:]:
        edit_reddit_post(
            config,
            db,
            show,
            stream,
            editing_episode,
            editing_episode.link or "",
            reddit_agent=None if config.debug else reddit_agent,
        )
    return True


def create_reddit_post(
    config: Config,
    db: DatabaseDatabase,
    show: Show,
    stream: Stream,
    episode: Episode,
    reddit_agent: RedditHolo | None = None,
) -> str | None:
    display_episode = stream.to_display_episode(episode)

    title, body = _create_post_contents(config, db, show, stream, display_episode)
    if not reddit_agent:
        return None
    new_post = reddit_agent.submit_text_post(title, body)
    if not new_post:
        logger.error("Failed to submit post")
        return None
    logger.debug("Post successful")
    return get_shortlink_from_id(new_post.id)


def edit_reddit_post(
    config: Config,
    db: DatabaseDatabase,
    show: Show,
    stream: Stream,
    episode: Episode,
    url: str,
    reddit_agent: RedditHolo | None = None,
) -> None:
    display_episode = stream.to_display_episode(episode)

    _, body = _create_post_contents(
        config, db, show, stream, display_episode, quiet=True
    )
    if reddit_agent:
        reddit_agent.edit_text_post(url, body)


def _create_post_contents(
    config: Config,
    db: DatabaseDatabase,
    show: Show,
    stream: Stream,
    episode: Episode,
    quiet: bool = False,
) -> tuple[str, str]:
    title = _create_post_title(config, show, episode)
    title = format_post_text(
        config, db, title, config.post_formats, show, episode, stream
    )
    logger.info("Title:\n%s", title)
    body = format_post_text(
        config, db, config.post_body, config.post_formats, show, episode, stream
    )
    if not quiet:
        logger.info("Body:\n%s", body)
    return title, body


def format_post_text(
    config: Config,
    db: DatabaseDatabase,
    text: str,
    formats: dict[str, str],
    show: Show,
    episode: Episode,
    stream: Stream,
) -> str:
    # TODO: change to a more block-based system (can exclude blocks without content)
    if "{spoiler}" in text:
        text = safe_format(text, spoiler=_gen_text_spoiler(formats, show))
    if "{streams}" in text:
        text = safe_format(text, streams=_gen_text_streams(db, formats, show))
    if "{links}" in text:
        text = safe_format(text, links=_gen_text_links(db, formats, show))
    if "{discussions}" in text:
        text = safe_format(
            text, discussions=_gen_text_discussions(db, formats, show, stream)
        )
    if "{aliases}" in text:
        text = safe_format(text, aliases=_gen_text_aliases(db, formats, show))
    if "{poll}" in text:
        text = safe_format(
            text, poll=_gen_text_poll(db, config, formats, show, episode)
        )

    episode_name = f": {episode.name}" if episode.name else ""
    episode_alt_number = (
        ""
        if stream.remote_offset == 0
        else f" ({episode.number + stream.remote_offset})"
    )
    text = safe_format(
        text,
        show_name=show.name,
        show_name_en=show.name_en,
        episode=episode.number,
        episode_alt_number=episode_alt_number,
        episode_name=episode_name,
    )
    return text.strip()


def _create_post_title(config: Config, show: Show, episode: Episode) -> str:
    if show.name_en:
        title = config.post_title_with_en
    else:
        title = config.post_title

    if episode.number == show.length and config.post_title_postfix_final:
        title += " " + config.post_title_postfix_final
    return title


# Generating text parts


def _gen_text_spoiler(formats: dict[str, str], show: Show) -> str:
    logger.debug(
        "Generating spoiler text for show %s, spoiler is %s", show, show.has_source
    )
    if show.has_source:
        return formats["spoiler"]
    return ""


def _gen_text_streams(db: DatabaseDatabase, formats: dict[str, str], show: Show) -> str:
    logger.debug("Generating stream text for show %s", show)
    stream_texts: list[str] = []

    streams = db.get_streams(show=show)
    for stream in streams:
        if not stream.active:
            continue
        service = db.get_service(id=stream.service)
        if not (service and service.enabled and service.use_in_post):
            continue
        service_handler = services.get_service_handler(service)
        if not service_handler:
            continue
        text = safe_format(
            formats["stream"],
            service_name=service.name,
            stream_link=service_handler.get_stream_link(stream),
        )
        stream_texts.append(text)

    lite_streams = db.get_lite_streams(show=show)
    for lite_stream in lite_streams:
        text = safe_format(
            formats["stream"],
            service_name=lite_stream.service_name,
            stream_link=lite_stream.url,
        )
        stream_texts.append(text)

    if stream_texts:
        return "\n".join(stream_texts)

    return "*None*"


def _gen_text_links(db: DatabaseDatabase, formats: dict[str, str], show: Show) -> str:
    logger.debug("Generating stream text for show %s", show)
    links = db.get_links(show=show)
    link_texts: list[str] = []
    link_texts_bottom: list[
        str
    ] = []  # for links that come last, e.g. official and subreddit
    for link in links:
        site = db.get_link_site(id=link.site)
        if not (site and site.enabled):
            continue
        link_handler = services.get_link_handler(site)
        if not link_handler:
            continue
        if site.key == "subreddit":
            text = safe_format(formats["link_reddit"], link=link_handler.get_link(link))
        else:
            text = safe_format(
                formats["link"],
                site_name=site.name,
                link=link_handler.get_link(link),
            )
        if site.key in {"subreddit", "official"}:
            link_texts_bottom.append(text)
        else:
            link_texts.append(text)

    return "\n".join(link_texts) + "\n" + "\n".join(link_texts_bottom)


_NUM_LINES = 13
_MAX_COLS = 4


def _gen_text_discussions(
    db: DatabaseDatabase, formats: dict[str, str], show: Show, stream: Stream
) -> str:
    episodes = db.get_episodes(show)
    logger.debug("Num previous episodes: %d", len(episodes))
    n_episodes = _MAX_COLS * _NUM_LINES
    if len(episodes) > n_episodes:
        logger.debug("Clipping to most recent %d episodes", n_episodes)
        episodes = episodes[-n_episodes:]
    if not episodes:
        return formats["discussion_none"]

    table: list[str] = []
    for episode in episodes:
        episode = stream.to_display_episode(episode)
        poll_handler = services.get_default_poll_handler()
        poll = db.get_poll(show, episode)
        if not poll:
            score = None
            poll_link = None
        elif poll.has_score:
            score = poll.score
            poll_link = poll_handler.get_results_link(poll)
        else:
            score = poll_handler.get_score(poll)
            poll_link = poll_handler.get_results_link(poll)
        score = poll_handler.convert_score_str(score)
        table.append(
            safe_format(
                formats["discussion"],
                episode=episode.number,
                link=episode.link,
                score=score,
                poll_link=poll_link if poll_link else "http://localhost",
            )
        )  # Need valid link even when empty

    num_columns = 1 + (len(table) - 1) // _NUM_LINES
    format_head, format_align = (
        formats["discussion_header"],
        formats["discussion_align"],
    )
    table_head = (
        "|".join(num_columns * [format_head])
        + "\n"
        + "|".join(num_columns * [format_align])
    )
    table = ["|".join(table[i::_NUM_LINES]) for i in range(_NUM_LINES)]
    return table_head + "\n" + "\n".join(table)


def _gen_text_aliases(db: DatabaseDatabase, formats: dict[str, str], show: Show) -> str:
    aliases = db.get_aliases(show)
    if not aliases:
        return ""
    return safe_format(formats["aliases"], aliases=", ".join(aliases))


def _gen_text_poll(
    db: DatabaseDatabase,
    config: Config,
    formats: dict[str, str],
    show: Show,
    episode: Episode,
) -> str:
    handler = services.get_default_poll_handler()
    title = config.post_poll_title.format(show=show.name, episode=episode.number)

    poll = db.get_poll(show, episode)
    if not poll:
        poll_id = handler.create_poll(
            title, headers={"User-Agent": config.useragent}, submit=not config.debug
        )
        if not poll_id:
            return ""
        site = db.get_poll_site(key=handler.key)
        db.add_poll(show, episode, site, poll_id)
        poll = db.get_poll(show, episode)

    if not poll:
        return ""

    poll_url = handler.get_link(poll)
    poll_results_url = handler.get_results_link(poll)
    return safe_format(
        formats["poll"], poll_url=poll_url, poll_results_url=poll_results_url
    )


# Helpers


class _SafeDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def safe_format(s: str, **kwargs: Any) -> str:
    """
    A safer version of the default str.format(...) function.
    Ignores unused keyword arguments and unused '{...}' placeholders instead of throwing a KeyError.
    :param s: The string being formatted
    :param kwargs: The format replacements
    :return: A formatted string
    """
    return s.format_map(_SafeDict(**kwargs))
