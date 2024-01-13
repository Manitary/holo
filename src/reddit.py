import logging

import praw
from praw.models import Comment, Submission, Subreddit
from praw.models.reddit.comment import CommentModeration
from praw.models.reddit.subreddit import SubredditFlair, SubredditLinkFlairTemplates

from config import Config

logger = logging.getLogger(__name__)


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
        self._subreddit: Subreddit = self._reddit.subreddit(config.subreddit)
        self._post_flair_id: str = config.post_flair_id
        self._post_flair_text: str = config.post_flair_text
        self._max_episodes: int = config.max_episodes

    @property
    def max_episodes(self) -> int:
        return self._max_episodes

    @property
    def subreddit(self) -> str:
        return self._subreddit.display_name

    def _get_flair_ids(self) -> list[str]:
        flair: SubredditFlair = self._subreddit.flair
        templates: SubredditLinkFlairTemplates = flair.link_templates
        flair_ids: list[str] = [
            str(ft["flair_template_id"]) for ft in templates.user_selectable()
        ]
        return flair_ids

    def submit_text_post(self, title: str, body: str) -> Submission | None:
        try:
            logger.info("Checking availability of flair %s", self._post_flair_id)
            if self._post_flair_id in self._get_flair_ids():
                flair_id, flair_text = (
                    self._post_flair_id,
                    self._post_flair_text,
                )
            else:
                logger.warning("Flair not selectable, flairing will be disabled")
                flair_id, flair_text = None, None

            logger.info("Submitting post to %s", self.subreddit)
            new_post: Submission = self._subreddit.submit(  # type: ignore
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
            post = self.get_text_post(url)
            if not post:
                return None
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

    def comment_post(self, submission: Submission, body: str) -> Comment:
        reply = submission.reply(body)
        assert isinstance(reply, Comment)
        return reply

    def sticky_comment(self, comment: Comment) -> None:
        comment_moderation = comment.mod
        assert isinstance(comment_moderation, CommentModeration)
        comment_moderation.distinguish(sticky=True)


def get_shortlink_from_id(submission_id: str) -> str:
    return f"http://redd.it/{submission_id}"


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
# 			logger.error("Failed to distinguish: %s", response["errors"])

# Utilities
