import logging
from collections import OrderedDict
from typing import Generator

import yaml

import services
from config import Config
from data.database import DatabaseDatabase
from data.models import ShowType, UnprocessedShow, UnprocessedStream

logger = logging.getLogger(__name__)


def main(
    config: Config,
    db: DatabaseDatabase,
    output_yaml: bool,
    output_file: str | None = None,
) -> None:
    if output_yaml and output_file:
        logger.debug("Using output file: %s", output_file)
        create_season_config(config, db, output_file)
    # check_new_shows(config, db, update_db=not config.debug)
    # check_new_shows(config, db)
    # match_show_streams(config, db, update_db=not config.debug)
    # match_show_streams(config, db)
    # check_new_streams(config, db, update_db=not config.debug)
    # check_new_streams(config, db)


# New shows

# Retain order of OrderedDict when dumping yaml
represent_dict_order = lambda self, data: self.represent_mapping(
    "tag:yaml.org,2002:map", data.items()
)
yaml.add_representer(OrderedDict, represent_dict_order)


def create_season_config(
    config: Config, db: DatabaseDatabase, output_file: str
) -> None:
    logger.info("Checking for new shows")
    shows = _get_primary_source_shows(config)

    logger.debug("Outputting new shows")
    with open(output_file, "w", encoding="utf-8") as f:
        yaml.dump_all(shows, f, explicit_start=True, default_flow_style=False)


def _get_primary_source_shows(config: Config):
    logger.debug("Retrieving primary show list")
    link_handlers = services.get_link_handlers()
    service_handlers = services.get_service_handlers()

    site_key = config.discovery_primary_source
    if site_key not in link_handlers:
        logger.warning("Primary source site handler for %s not installed", site_key)
        return

    site_handler = link_handlers.get(site_key)
    shows = []
    for raw_show in site_handler.get_seasonal_shows(useragent=config.useragent):
        if (
            raw_show.show_type is not ShowType.UNKNOWN
            and raw_show.show_type not in config.new_show_types
        ):
            logger.debug("  Show isn't an allowed type (%s)", raw_show.show_type)
            logger.debug("    name=%s", raw_show.name)
            continue

        logger.debug("New show: %s", raw_show.name)

        d = OrderedDict(
            [
                ("title", raw_show.name),
                ("type", raw_show.show_type.name.lower()),
                ("has_source", raw_show.has_source),
                (
                    "info",
                    OrderedDict(
                        [
                            (i, "")
                            for i in sorted(link_handlers.keys())
                            if i in config.discovery_secondary_sources
                        ]
                    ),
                ),
                (
                    "streams",
                    OrderedDict(
                        [
                            (s, "")
                            for s in sorted(service_handlers.keys())
                            if not service_handlers[s].is_generic
                            and s in config.discovery_stream_sources
                        ]
                    ),
                ),
            ]
        )
        shows.append(d)

    return shows


#############
# OLD STUFF #
#############


def check_new_shows(
    config: Config, db: DatabaseDatabase, update_db: bool = True
) -> None:
    logger.info("Checking for new shows")
    for raw_show in _get_new_season_shows(config, db):
        if (
            raw_show.show_type is not ShowType.UNKNOWN
            and raw_show.show_type not in config.new_show_types
        ):
            logger.debug("  Show isn't an allowed type (%s)", raw_show.show_type)
            logger.debug("    name=%s", raw_show.name)
            continue

        if db.has_link(raw_show.site_key, raw_show.show_key):
            continue

        # Link doesn't doesn't exist in db
        logger.debug("New show link: %s on %s", raw_show.show_key, raw_show.site_key)

        # Check if related to existing show
        shows = db.search_show_ids_by_names(raw_show.name, *raw_show.more_names)

        if len(shows) > 1:
            # Uh oh, multiple matches
            # TODO: make sure this isn't triggered by multi-season shows
            logger.warning("  More than one show found, ids=%s", shows)
            # show_id = shows[-1]
            continue

        show_id = None
        if not shows:
            # Show doesn't exist; add it
            logger.debug("  Show not found, adding to database")
            if update_db:
                show_id = db.add_show(raw_show, commit=False)
        elif len(shows) == 1:
            show_id = shows.pop()

        # Add link to show
        if show_id and update_db:
            db.add_link(raw_show, show_id, commit=False)

        if update_db:
            db.commit()


def _get_new_season_shows(
    config: Config, db: DatabaseDatabase
) -> Generator[UnprocessedShow, None, None]:
    # Only checks link sites because their names are preferred
    # Names on stream sites are unpredictable and many times in english
    handlers = services.get_link_handlers()
    for site in db.get_link_sites():
        if site.key not in handlers:
            logger.warning("Link site handler for %s not installed", site.key)
            continue

        handler = handlers.get(site.key)
        if not handler:
            continue
        logger.info("  Checking %s (%s)", handler.name, handler.key)
        raw_shows = handler.get_seasonal_shows(useragent=config.useragent)
        for raw_show in raw_shows:
            yield raw_show


# New streams


def check_new_streams(
    config: Config, db: DatabaseDatabase, update_db: bool = True
) -> None:
    logger.info("Checking for new streams")
    for raw_stream in _get_new_season_streams(config, db):
        if db.has_stream(raw_stream.service_key, raw_stream.show_key):
            logger.debug(
                "  Stream already exists for %s on %s",
                raw_stream.show_key,
                raw_stream.service_key,
            )
            continue

        logger.debug("  %s", raw_stream.name)

        # Search for a related show
        shows = db.search_show_ids_by_names(raw_stream.name)
        show_id = None
        if len(shows) == 0:
            logger.debug("    Show not found")
        elif len(shows) == 1:
            show_id = shows.pop()
        else:
            # Uh oh, multiple matches
            # TODO: make sure this isn't triggered by multi-season shows
            logger.warning("    More than one show found, ids=%s", shows)

        # Add stream
        if update_db:
            db.add_stream(raw_stream, show_id, commit=False)

    if update_db:
        db.commit()


def _get_new_season_streams(
    config: Config, db: DatabaseDatabase
) -> Generator[UnprocessedStream, None, None]:
    handlers = services.get_service_handlers()
    for service in db.get_services():
        if service.key not in handlers:
            logger.warning("Service handler for %s not installed", service.key)
            continue
        if not service.enabled:
            continue
        handler = handlers.get(service.key)
        if not handler:
            continue
        logger.info("  Checking %s (%s)", handler.name, handler.key)
        raw_streams = handler.get_seasonal_streams(useragent=config.useragent)
        for raw_stream in raw_streams:
            yield raw_stream


# Match streams missing shows


def match_show_streams(
    config: Config, db: DatabaseDatabase, update_db: bool = True
) -> None:
    logger.info("Matching streams to shows")
    streams = db.get_streams(unmatched=True)

    if not streams:
        logger.debug("  No unmatched streams")
        return

    # Check each link site
    for site in db.get_link_sites():
        logger.debug("  Checking service: %s", site.key)
        handler = services.get_link_handler(site)
        if not handler:
            continue

        # Check remaining streams
        for stream in list(streams):  # Iterate over copy of stream list allow removals
            logger.debug("    Checking stream: %s", stream.name)
            raw_shows = handler.find_show(stream.name, useragent=config.useragent)
            if not raw_shows:
                logger.warning("    No shows found")
                continue

            if len(raw_shows) > 1:
                logger.warning("    Multiple shows found")
                continue

            # Show info found
            raw_show = raw_shows.pop()
            logger.debug("      Found show: %s", raw_show.name)

            # Search stored names for show matches
            shows = db.search_show_ids_by_names(raw_show.name, *raw_show.more_names)
            if not shows:
                logger.warning("      No shows known")
            if len(shows) > 1:
                logger.warning("      Multiple shows known")
            # All the planets are aligned
            # Connect the stream and show and save the used name
            show_id = shows.pop()
            if update_db:
                db.update_stream(stream, show=show_id, active=True)
                db.add_show_names(stream.name, id=show_id, commit=False)
            streams.remove(stream)

        if update_db:
            db.commit()
