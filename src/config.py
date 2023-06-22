import configparser
import logging

from data.models import ShowType, str_to_showtype

logger = logging.getLogger(__name__)


class WhitespaceFriendlyConfigParser(configparser.ConfigParser):
    def get(self, section, option, *args, **kwargs) -> str:  # type:ignore
        val = super().get(section, option, *args, **kwargs)  # type:ignore
        return val.strip('"')


class Config:
    def __init__(self) -> None:
        self.debug: bool = False
        self.log_dir: str | None = None
        self.module: str | None = None
        self.database: str = ""
        self.useragent: str | None = None
        self.ratelimit: float = 1.0

        self.subreddit: str | None = None
        self.r_username: str | None = None
        self.r_password: str | None = None
        self.r_oauth_key: str | None = None
        self.r_oauth_secret: str | None = None

        self.services: dict[str, dict[str, str]] = {}

        self.new_show_types: list[ShowType] = []
        self.record_scores: bool = False

        self.discovery_primary_source: str | None = None
        self.discovery_secondary_sources: list[str] = []
        self.discovery_stream_sources: list[str] = []

        self.post_title: str = ""
        self.post_title_with_en: str = ""
        self.post_title_postfix_final: str | None = None
        self.post_flair_id: str | None = None
        self.post_flair_text: str | None = None
        self.post_body: str = ""
        self.post_poll_title: str = ""
        self.batch_thread_post_title: str | None = None
        self.batch_thread_post_title_with_en: str | None = None
        self.batch_thread_post_body: str | None = None
        self.post_formats: dict[str, str] = {}


def from_file(file_path: str) -> Config | None:
    if file_path.find(".") < 0:
        file_path += ".ini"

    parsed = WhitespaceFriendlyConfigParser()
    success = parsed.read(file_path, encoding="utf-8")
    if len(success) == 0:
        print("Failed to load config file")
        return None

    config = Config()

    if "data" in parsed:
        sec = parsed["data"]
        config.database = sec.get("database", "")

    if "connection" in parsed:
        sec = parsed["connection"]
        config.useragent = sec.get("useragent", None)
        config.ratelimit = sec.getfloat("ratelimit", 1.0)

    if "reddit" in parsed:
        sec = parsed["reddit"]
        config.subreddit = sec.get("subreddit", None)
        config.r_username = sec.get("username", None)
        config.r_password = sec.get("password", None)
        config.r_oauth_key = sec.get("oauth_key", None)
        config.r_oauth_secret = sec.get("oauth_secret", None)

    if "options" in parsed:
        sec = parsed["options"]
        config.debug = sec.getboolean("debug", False)

        config.new_show_types.extend(
            map(
                lambda s: str_to_showtype(s.strip()),
                sec.get("new_show_types", "").split(" "),
            )
        )
        config.record_scores = sec.getboolean("record_scores", False)

    if "options.discovery" in parsed:
        sec = parsed["options.discovery"]
        config.discovery_primary_source = sec.get("primary_source", None)
        config.discovery_secondary_sources = sec.get("secondary_sources", "").split(" ")
        config.discovery_stream_sources = sec.get("stream_sources", "").split(" ")

    if "post" in parsed:
        sec = parsed["post"]
        config.post_title = sec.get("title", "")
        config.post_title_with_en = sec.get("title_with_en", "")
        config.post_title_postfix_final = sec.get("title_postfix_final", None)
        config.post_flair_id = sec.get("flair_id", None)
        config.post_flair_text = sec.get("flair_text", None)
        config.post_body = sec.get("body", "")
        config.post_poll_title = sec.get("poll_title", "")
        config.batch_thread_post_title = sec.get("batch_thread_title", None)
        config.batch_thread_post_title_with_en = sec.get(
            "batch_thread_title_with_en", None
        )
        config.batch_thread_post_body = sec.get("batch_thread_body", None)
        for key in sec:
            if key.startswith("format_") and len(key) > 7:
                config.post_formats[key[7:]] = sec[key]

    # Services
    for key in parsed:
        if key.startswith("service."):
            service = key[8:]
            config.services[service] = dict(parsed[key])

    return config


def validate(config: Config) -> str | bool:
    def is_bad_str(s: str | None) -> bool:
        return s is None or len(s) == 0

    if is_bad_str(config.database):
        return "database missing"
    if is_bad_str(config.useragent):
        return "useragent missing"
    if config.ratelimit < 0:
        logger.warning("Rate limit can't be negative, defaulting to 1.0")
        config.ratelimit = 1.0
    if is_bad_str(config.subreddit):
        return "subreddit missing"
    if is_bad_str(config.r_username):
        return "reddit username missing"
    if is_bad_str(config.r_password):
        return "reddit password missing"
    if is_bad_str(config.r_oauth_key):
        return "reddit oauth key missing"
    if is_bad_str(config.r_oauth_secret):
        return "reddit oauth secret missing"
    if is_bad_str(config.post_title):
        return "post title missing"
    if is_bad_str(config.post_body):
        return "post title missing"
    return False
