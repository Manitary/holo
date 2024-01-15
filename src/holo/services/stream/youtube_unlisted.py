import logging

from . import youtube

logger = logging.getLogger(__name__)


class ServiceHandler(youtube.ServiceHandler):
    def __init__(self) -> None:
        super(youtube.ServiceHandler, self).__init__(
            key="youtube_unlisted", name="Youtube (Unlisted)", is_generic=False
        )
