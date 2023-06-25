import logging

from services.stream import youtube

logger = logging.getLogger(__name__)


class ServiceHandler(youtube.ServiceHandler):
    def __init__(self):
        super(youtube.ServiceHandler, self).__init__(key="anione", name="Ani-One", is_generic=False)
