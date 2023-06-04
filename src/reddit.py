import logging

import praw
from praw.models import Submission

from config import Config

logger = logging.getLogger(__name__)

# Initialization

_r: praw.Reddit | None = None
_config: Config | None = None


def init_reddit(config: Config) -> None:
	global _config
	_config = config


def _connect_reddit() -> praw.Reddit | None:
	if _config is None:
		logger.error("Can't connect to reddit without a config")
		return None

	return praw.Reddit(
		client_id=_config.r_oauth_key,
		client_secret=_config.r_oauth_secret,
		username=_config.r_username,
		password=_config.r_password,
		user_agent=_config.useragent,
		check_for_updates=False,
	)


def _ensure_connection() -> bool:
	global _r
	if _r is None:
		_r = _connect_reddit()
	return _r is not None


class RedditHolo:
	def __init__(self, config: Config) -> None:
		self._reddit: praw.Reddit = praw.Reddit(
			client_id=config.r_oauth_key,
			client_secret=config.r_oauth_secret,
			username=config.r_username,
			password=config.r_password,
			user_agent=config.useragent,
			check_for_updates=False,
		)
		self._config: Config = config

	def submit_text_post(
		self, subreddit: str, title: str, body: str
	) -> Submission | None:
		try:
			logger.info("Checking availability of flair %s", self._config.post_flair_id)
			flair_ids: dict[str, str | bool] = [
				ft["flair_template_id"]
				for ft in self._reddit.subreddit(subreddit).flair.link_templates.user_selectable()  # type: ignore
			]
			if self._config.post_flair_id in flair_ids:
				flair_id, flair_text = (
					self._config.post_flair_id,
					self._config.post_flair_text,
				)
			else:
				logger.warning("Flair not selectable, flairing will be disabled")
				flair_id, flair_text = None, None

			logger.info("Submitting post to %s", subreddit)
			new_post: Submission = self._reddit.subreddit(subreddit).submit(  # type: ignore
				title,
				selftext=body,
				flair_id=flair_id,
				flair_text=flair_text,
				send_replies=False,
			)
			return new_post  # type: ignore
		except Exception:
			logger.exception("Failed to submit text post")
			return None

	def edit_text_post(self, url: str, body: str) -> Submission | None:
		try:
			logger.info("Editing post %s", url)
			post: Submission = get_text_post(url)  # type: ignore
			post.edit(body=body)  # type: ignore
			return post
		except Exception:
			logger.exception("Failed to submit text post")
			return None

	def get_text_post(self, url: str) -> Submission | None:
		try:
			new_post: Submission = self._reddit.submission(url=url)  # type: ignore
			return new_post  # type: ignore
		except Exception:
			logger.exception("Failed to retrieve text post")
			return None


# Thing doing


def submit_text_post(subreddit: str, title: str, body: str) -> Submission | None:
	_ensure_connection()
	try:
		logger.info("Checking availability of flair %s", _config.post_flair_id)
		flair_ids = [
			ft["flair_template_id"]
			for ft in _r.subreddit(subreddit).flair.link_templates.user_selectable()
		]
		if _config.post_flair_id in flair_ids:
			flair_id, flair_text = _config.post_flair_id, _config.post_flair_text
		else:
			logger.warning("Flair not selectable, flairing will be disabled")
			flair_id, flair_text = None, None

		logger.info("Submitting post to %s", subreddit)
		new_post = _r.subreddit(subreddit).submit(
			title,
			selftext=body,
			flair_id=flair_id,
			flair_text=flair_text,
			send_replies=False,
		)
		return new_post
	except Exception:
		logger.exception("Failed to submit text post")
		return None


def edit_text_post(url: str, body: str) -> Submission | None:
	_ensure_connection()
	try:
		logger.info("Editing post %s", url)
		post = get_text_post(url)
		post.edit(body)
		return post
	except Exception:
		logger.exception("Failed to submit text post")
		return None


def get_text_post(url: str) -> Submission | None:
	_ensure_connection()
	try:
		new_post = _r.submission(url=url)
		return new_post
	except Exception:
		logger.exception("Failed to retrieve text post")
		return None


# NOTE: PRAW3 stuff
# def send_modmail(subreddit, title, body):
# 	_ensure_connection()
# 	_r.send_message("/r/"+subreddit, title, body)
#
# def send_pm(user, title, body, from_sr=None):
# 	_ensure_connection()
# 	_r.send_message(user, title, body, from_sr=from_sr)
#
# def reply_to(thing, body, distinguish=False):
# 	_ensure_connection()
#
# 	reply = thing.reply(body)
#
# 	if distinguish and reply is not None:
# 		response = reply.distinguish()
# 		if len(response) > 0 and len(response["errors"]) > 0:
# 			error("Failed to distinguish: {}".format(response["errors"]))

# Utilities


def get_shortlink_from_id(submission_id: str) -> str:
	# TODO Verify if it can be changed to https without breaking anything
	return f"http://redd.it/{submission_id}"
