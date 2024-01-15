import logging

from .config import Config
from .data.database import DatabaseDatabase
from .data.models import Episode, Stream
from .reddit import RedditHolo
from .services import Handlers
from .submission import SubmissionBuilder

logger = logging.getLogger(__name__)


def main(
    config: Config,
    db: DatabaseDatabase,
    handlers: Handlers,
    show_name: str,
    episode_count: str | int,
) -> None:
    episode_count = int(episode_count)
    reddit_holo = None if config.debug else RedditHolo(config=config)
    submitter = SubmissionBuilder(db=db, config=config, services=handlers)
    show = db.get_show_by_name(show_name)
    if not show:
        raise ValueError(f"Show {show_name} does not exist!")
    stream = Stream.from_show(show)

    post_urls: list[str] = []
    for i in range(1, episode_count + 1):
        submitter.set_data(
            show=show, episode=Episode(number=i), stream=stream, raw=True
        )
        post_url = submitter.create_reddit_post(
            reddit_agent=reddit_holo,
        )
        logger.info("  Post URL: %s", post_url)
        if post_url:
            post_url = post_url.replace("http:", "https:")
            db.add_episode(show, i, post_url)
        else:
            logger.error("  Episode not submitted")
        post_urls.append(str(post_url))

    for editing_episode in db.get_episodes(show):
        submitter.set_data(episode=editing_episode, show=show, stream=stream)
        submitter.edit_reddit_post(
            editing_episode.link or "",
            reddit_agent=reddit_holo,
        )

    submitter.set_data(
        show=show, stream=stream, episode=Episode(number=episode_count), raw=True
    )
    megathread_url = submitter.create_reddit_post(batch=True, reddit_agent=reddit_holo)

    if megathread_url:
        logger.debug("Post successful")
        megathread_url.replace("http:", "https:")
    else:
        logger.error("Failed to submit post")

    db.set_show_enabled(show, False, commit=not config.debug)

    for i, url in enumerate(post_urls):
        logger.info("Episode %d: %s", i, url)
    logger.info("Megathread: %s", megathread_url)
