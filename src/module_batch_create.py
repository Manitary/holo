import logging

import reddit
from config import Config
from data.database import DatabaseDatabase
from data.models import Episode, Show, Stream
from module_find_episodes import (
	_create_reddit_post,
	_edit_reddit_post,
	_format_post_text,
)

logger = logging.getLogger(__name__)


def main(
	config: Config, db: DatabaseDatabase, show_name: str, episode_count: str
) -> None:
	int_episode_count = int(episode_count)
	reddit.init_reddit(config)

	show = db.get_show_by_name(show_name)
	if not show:
		raise IOError(f"Show {show_name} does not exist!")
	stream = Stream.from_show(show)

	post_urls: list[str] = []
	for i in range(1, int_episode_count + 1):
		int_episode = Episode(number=i, name="", link="", date=None)
		post_url = _create_reddit_post(
			config, db, show, stream, int_episode, submit=not config.debug
		)
		logger.info("  Post URL: %s", post_url)
		if not post_url:
			logger.error("  Episode not submitted")
			continue
		post_url = post_url.replace("http:", "https:")
		db.add_episode(show, int_episode.number, post_url)
		post_urls.append(post_url)

	for editing_episode in db.get_episodes(show):
		_edit_reddit_post(
			config,
			db,
			show,
			stream,
			editing_episode,
			editing_episode.link,
			submit=not config.debug,
		)

	megathread_title, megathread_body = _create_megathread_content(
		config, db, show, stream, int_episode_count
	)

	if not config.debug:
		megathread_post = reddit.submit_text_post(
			config.subreddit or "", megathread_title, megathread_body
		)
	else:
		megathread_post = None

	if megathread_post is not None:
		logger.debug("Post successful")
		megathread_url = reddit.get_shortlink_from_id(megathread_post.id).replace(
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
	config: Config, db: DatabaseDatabase, show: Show, stream: Stream, episode_count: int
) -> tuple[str, str]:
	title = _create_megathread_title(config, show, episode_count)
	title = _format_post_text(
		config,
		db,
		title,
		config.post_formats,
		show,
		Episode(number=episode_count, name="", link="", date=None),
		stream,
	)
	logger.info("Title:\n%s", title)

	body = _format_post_text(
		config,
		db,
		config.batch_thread_post_body,
		config.post_formats,
		show,
		Episode(number=episode_count, name="", link="", date=None),
		stream,
	)
	logger.info("Body:\n%s", body)
	return title, body


def _create_megathread_title(config: Config, show: Show, episode_count: int) -> str:
	if show.name_en:
		title = config.batch_thread_post_title_with_en
	else:
		title = config.batch_thread_post_title
	return title or ""
