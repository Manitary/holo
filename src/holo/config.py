import configparser
import logging
from dataclasses import dataclass, field
from typing import Self

from data.models import ShowType, str_to_showtype

logger = logging.getLogger(__name__)


class InvalidConfigException(Exception):
    ...


class WhitespaceFriendlyConfigParser(configparser.ConfigParser):
    def get(self, section, option, *args, **kwargs) -> str:  # type:ignore
        val = super().get(section, option, *args, **kwargs)  # type:ignore
        return val.strip('"')


@dataclass
class Config:
    debug: bool = False
    log_dir: str = ""
    module: str = "episode"
    database: str = ""
    useragent: str = ""
    ratelimit: float = 1.0
    subreddit: str = ""
    r_username: str = ""
    r_password: str = ""
    r_oauth_key: str = ""
    r_oauth_secret: str = ""
    services: dict[str, dict[str, str]] = field(default_factory=dict)
    new_show_types: list[ShowType] = field(default_factory=list)
    record_scores: bool = False
    discovery_primary_source: str = ""
    discovery_secondary_sources: list[str] = field(default_factory=list)
    discovery_stream_sources: list[str] = field(default_factory=list)
    post_title: str = ""
    post_title_with_en: str = ""
    post_title_postfix_final: str = ""
    post_flair_id: str = ""
    post_flair_text: str = ""
    post_body: str = ""
    post_poll_title: str = ""
    batch_thread_post_title: str = ""
    batch_thread_post_title_with_en: str = ""
    batch_thread_post_body: str = ""
    post_formats: dict[str, str] = field(default_factory=dict)
    max_episodes: int = 5
    source_material_corner: str = ""

    @classmethod
    def from_file(cls, file_path: str) -> Self:
        if "." not in file_path:
            file_path += ".ini"

        parsed = WhitespaceFriendlyConfigParser(comment_prefixes=(";",))
        success = parsed.read(file_path, encoding="utf-8")
        if not success:
            logger.exception("Failed to load config file: %s", file_path)
            raise InvalidConfigException("Failed to load config file")

        config = Config()

        if "data" in parsed:
            sec = parsed["data"]
            config.database = sec.get("database", "")

        if "connection" in parsed:
            sec = parsed["connection"]
            config.useragent = sec.get("useragent", "")
            config.ratelimit = sec.getfloat("ratelimit", 1.0)

        if "reddit" in parsed:
            sec = parsed["reddit"]
            config.subreddit = sec.get("subreddit", "")
            config.r_username = sec.get("username", "")
            config.r_password = sec.get("password", "")
            config.r_oauth_key = sec.get("oauth_key", "")
            config.r_oauth_secret = sec.get("oauth_secret", "")
            config.max_episodes = sec.getint("max_posts", 5)

        if "options" in parsed:
            sec = parsed["options"]
            config.debug = sec.getboolean("debug", False)

            config.new_show_types.extend(
                map(
                    str_to_showtype,
                    sec.get("new_show_types", "").split(),
                )
            )
            config.record_scores = sec.getboolean("record_scores", False)

        if "options.discovery" in parsed:
            sec = parsed["options.discovery"]
            config.discovery_primary_source = sec.get("primary_source", "")
            config.discovery_secondary_sources = sec.get(
                "secondary_sources", ""
            ).split()
            config.discovery_stream_sources = sec.get("stream_sources", "").split()

        if "post" in parsed:
            sec = parsed["post"]
            config.post_title = sec.get("title", "")
            config.post_title_with_en = sec.get("title_with_en", "")
            config.post_title_postfix_final = sec.get("title_postfix_final", "")
            config.post_flair_id = sec.get("flair_id", "")
            config.post_flair_text = sec.get("flair_text", "")
            config.post_body = sec.get("body", "")
            config.post_poll_title = sec.get("poll_title", "")
            config.batch_thread_post_title = sec.get("batch_thread_title", "")
            config.batch_thread_post_title_with_en = sec.get(
                "batch_thread_title_with_en", ""
            )
            config.batch_thread_post_body = sec.get("batch_thread_body", "")
            for key in sec:
                if key.startswith("format_") and len(key) > 7:
                    config.post_formats[key[7:]] = sec[key]

        if "comment" in parsed:
            sec = parsed["comment"]
            config.source_material_corner = sec.get("source_material_corner", "")

        # Services
        for key in parsed:
            if key.startswith("service."):
                config.services[key[8:]] = dict(parsed[key])

        return config

    @property
    def is_valid(self) -> bool:
        if not self.database:
            logger.warning("database missing")
            return False
        if not self.useragent:
            logger.warning("useragent missing")
            return False
        if self.ratelimit < 0:
            logger.warning("Rate limit can't be negative, defaulting to 1.0")
            self.ratelimit = 1.0
        if not self.subreddit:
            logger.warning("subreddit missing")
            return False
        if not self.r_username:
            logger.warning("reddit username missing")
            return False
        if not self.r_password:
            logger.warning("reddit password missing")
            return False
        if not self.r_oauth_key:
            logger.warning("reddit oauth key missing")
            return False
        if not self.r_oauth_secret:
            logger.warning("reddit oauth secret missing")
            return False
        if not self.post_title:
            logger.warning("post title missing")
            return False
        if not self.post_body:
            logger.warning("post title missing")
            return False
        return True
