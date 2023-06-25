import logging

from config import Config
from data.database import DatabaseDatabase
from data.models import Episode, Show, Stream
from module_find_episodes import create_reddit_post, edit_reddit_post, format_post_text
from reddit import RedditHolo, get_shortlink_from_id
from services import Handlers

logger = logging.getLogger(__name__)


def main(
    config: Config,
    db: DatabaseDatabase,
    handlers: Handlers,
    show_name: str,
    episode_count: str,
) -> None:
    int_episode_count = int(episode_count)
    reddit_holo = RedditHolo(config=config)
    show = db.get_show_by_name(show_name)
    if not show:
        raise IOError(f"Show {show_name} does not exist!")
    stream = Stream.from_show(show)

    post_urls: list[str] = []
    for i in range(1, int_episode_count + 1):
        int_episode = Episode(number=i)
        post_url = create_reddit_post(
            config,
            db,
            handlers,
            show,
            stream,
            int_episode,
            reddit_agent=None if config.debug else reddit_holo,
        )
        logger.info("  Post URL: %s", post_url)
        if post_url:
            post_url = post_url.replace("http:", "https:")
            db.add_episode(show, int_episode.number, post_url)
        else:
            logger.error("  Episode not submitted")
        post_urls.append(str(post_url))

    for editing_episode in db.get_episodes(show):
        edit_reddit_post(
            config,
            db,
            handlers,
            show,
            stream,
            editing_episode,
            editing_episode.link or "",
            reddit_agent=None if config.debug else reddit_holo,
        )

    megathread_title, megathread_body = _create_megathread_content(
        config, db, handlers, show, stream, int_episode_count
    )

    megathread_post = (
        None
        if config.debug
        else reddit_holo.submit_text_post(megathread_title, megathread_body)
    )

    if megathread_post:
        logger.debug("Post successful")
        megathread_url = get_shortlink_from_id(megathread_post.id).replace(
            "http:", "https:"
        )
    else:
        logger.error("Failed to submit post")
        megathread_url = None

    db.set_show_enabled(show, False, commit=not config.debug)

    for i, url in enumerate(post_urls):
        logger.info("Episode %d: %s", i, url)
    logger.info("Megathread: %s", megathread_url)


def _create_megathread_content(
    config: Config,
    db: DatabaseDatabase,
    handlers: Handlers,
    show: Show,
    stream: Stream,
    episode_count: int,
) -> tuple[str, str]:
    title = _create_megathread_title(config, show)
    title = format_post_text(
        config,
        db,
        handlers,
        title,
        config.post_formats,
        show,
        Episode(number=episode_count),
        stream,
    )
    logger.info("Title:\n%s", title)

    body = format_post_text(
        config,
        db,
        handlers,
        config.batch_thread_post_body,
        config.post_formats,
        show,
        Episode(number=episode_count),
        stream,
    )
    logger.info("Body:%s", body)
    return title, body


def _create_megathread_title(config: Config, show: Show) -> str:
    if show.name_en:
        return config.batch_thread_post_title_with_en
    return config.batch_thread_post_title
