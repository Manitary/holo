import logging

from config import Config
from data.database import DatabaseDatabase
from data.models import Episode, Stream
from module_find_episodes import _create_reddit_post, _edit_reddit_post
from reddit import RedditHolo

logger = logging.getLogger(__name__)


def main(
    config: Config, db: DatabaseDatabase, show_name: str, episode: str | int
) -> bool:
    int_episode = Episode(number=int(episode))
    reddit_holo = RedditHolo(config=config)
    show = db.get_show_by_name(show_name)
    if not show:
        raise IOError(f"Show {show_name} does not exist!")
    stream = Stream.from_show(show)

    post_url = _create_reddit_post(
        config,
        db,
        show,
        stream,
        int_episode,
        reddit_agent=None if config.debug else reddit_holo,
    )
    logger.info("  Post URL: %s", post_url)
    if not post_url:
        logger.error("  Episode not submitted")
        return False

    post_url = post_url.replace("http:", "https:")
    db.add_episode(show, int_episode.number, post_url)
    if show.delayed:
        db.set_show_delayed(show, False)
    for editing_episode in db.get_episodes(show):
        _edit_reddit_post(
            config,
            db,
            show,
            stream,
            editing_episode,
            editing_episode.link or "",
            reddit_agent=None if config.debug else reddit_holo,
        )
    return True
