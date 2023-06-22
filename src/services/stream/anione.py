import re
from datetime import datetime, timedelta

from .. import AbstractServiceHandler
from data.models import Episode, UnprocessedStream

from services.stream import youtube
import logging

logger = logging.getLogger(__name__)


class ServiceHandler(youtube.ServiceHandler):
    def __init__(self):
        super(youtube.ServiceHandler, self).__init__("anione", "Ani-One", False)
