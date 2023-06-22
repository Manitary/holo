import logging

from services.stream import youtube

logger = logging.getLogger(__name__)


class ServiceHandler(youtube.ServiceHandler):
    def __init__(self) -> None:
        super(youtube.ServiceHandler, self).__init__("museasia", "Muse Asia", False)
