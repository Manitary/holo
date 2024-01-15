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
    episode_number: str | int,
) -> bool:
    submitter = SubmissionBuilder(db=db, config=config, services=handlers)
    episode = Episode(number=int(episode_number))
    reddit_holo = RedditHolo(config=config)
    show = db.get_show_by_name(show_name)
    if not show:
        raise ValueError(f"Show {show_name} does not exist!")
    stream = Stream.from_show(show)
    submitter.set_data(show=show, episode=episode, stream=stream, raw=True)

    post_url = submitter.create_reddit_post(
        reddit_agent=None if config.debug else reddit_holo,
    )
    logger.info("  Post URL: %s", post_url)
    if not post_url:
        logger.error("  Episode not submitted")
        return False

    post_url = post_url.replace("http:", "https:")
    db.add_episode(show, episode.number, post_url)
    if show.delayed:
        db.set_show_delayed(show, False)
    for editing_episode in db.get_episodes(show):
        submitter.set_data(episode=editing_episode, show=show, stream=stream)
        submitter.edit_reddit_post(
            editing_episode.link or "",
            reddit_agent=None if config.debug else reddit_holo,
        )
    return True
