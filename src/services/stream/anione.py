import logging

from services.stream import youtube

logger = logging.getLogger(__name__)


class ServiceHandler(youtube.ServiceHandler):
    def __init__(self):
        super(youtube.ServiceHandler, self).__init__("anione", "Ani-One", False)
