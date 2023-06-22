import logging

import yaml

import services
from config import Config
from data.database import DatabaseDatabase
from data.models import ShowType, UnprocessedShow, UnprocessedStream, str_to_showtype

logger = logging.getLogger(__name__)


def main(config: Config, db: DatabaseDatabase, edit_file: str) -> None:
    if edit_file:
        if _edit_with_file(db, edit_file):
            logger.info("Edit successful; saving")
            db.commit()
        else:
            logger.error("Edit failed; reverting")
            db.rollback()
    else:
        logger.warning("Nothing to do")


def _edit_with_file(db: DatabaseDatabase, edit_file: str) -> bool | None:
    logger.info('Parsing show edit file "%s"', edit_file)
    try:
        with open(edit_file, "r", encoding="UTF-8") as f:
            parsed = list(yaml.full_load_all(f))
    except yaml.YAMLError:
        logger.exception("Failed to parse edit file")
        return

    logger.debug("  num shows=%d", len(parsed))

    for doc in parsed:
        name = doc["title"]
        name_en = doc.get("title_en", "")
        stype = str_to_showtype(doc.get("type", "tv"))  # convert to enum?
        length = doc.get("length", 0)
        has_source = doc.get("has_source", False)
        is_nsfw = doc.get("is_nsfw", False)

        logger.info('Adding show "%s" (%s)', name, stype)
        logger.debug("  has_source=%s", has_source)
        logger.debug("  is_nsfw=%s", is_nsfw)
        if stype == ShowType.UNKNOWN:
            logger.error('Invalid show type "%s"', stype)
            return False

        show = UnprocessedShow(
            name=name,
            name_en=name_en,
            show_type=stype,
            episode_count=length,
            has_source=has_source,
            is_nsfw=is_nsfw,
        )
        found_ids = db.search_show_ids_by_names(name, exact=True)
        logger.debug("Found ids: %s", found_ids)
        if len(found_ids) == 0:
            show_id = db.add_show(show, commit=False)
        elif len(found_ids) == 1:
            show_id = found_ids.pop()
            db.update_show(show_id, show, commit=False)
        else:
            logger.error("More than one ID found for show")
            return False

        # Info
        if "info" in doc:
            infos = doc["info"]
            for info_key in infos:
                url = infos[info_key]
                if not url:
                    continue

                logger.debug("  Info %s: %s", info_key, url)
                info_handler = services.get_link_handler(key=info_key)
                if info_handler:
                    info_id = info_handler.extract_show_id(url)
                    logger.debug("    id=%s", info_id)

                    if not db.has_link(info_key, info_id, show_id):
                        show.site_key = info_key
                        show.show_key = info_id
                        db.add_link(show, show_id, commit=False)
                else:
                    logger.error("    Info handler not installed")

        # Streams
        if "streams" in doc:
            streams = doc["streams"]
            for service_key in streams:
                url = streams[service_key]
                if not url:
                    continue
                remote_offset = 0
                try:
                    roi = url.rfind("|")
                    if roi > 0:
                        if roi + 1 < len(url):
                            remote_offset = int(url[roi + 1 :])
                        url = url[:roi]
                except Exception:
                    logger.exception('Improperly formatted stream URL "%s"', url)
                    continue

                logger.info("  Stream %s: %s", service_key, url)

                service_id = service_key.split("|")[0]
                stream_handler = services.get_service_handler(key=service_id)
                if stream_handler:
                    show_key = stream_handler.extract_show_key(url)
                    logger.debug("    id=%s", show_key)

                    if not db.has_stream(service_id, show_key):
                        s = UnprocessedStream(
                            service_key=service_id,
                            show_key=show_key,
                            remote_offset=remote_offset,
                            display_offset=0,
                        )
                        db.add_stream(s, show_id, commit=False)
                    else:
                        service = db.get_service(key=service_id)
                        s = db.get_stream(service_tuple=(service, show_key))
                        db.update_stream(
                            s, show=show_id, remote_offset=remote_offset, commit=False
                        )
                elif "|" in service_key:
                    # Lite stream
                    service, service_name = service_key.split("|", maxsplit=1)
                    db.add_lite_stream(show_id, service, service_name, url)
                else:
                    logger.error("    Stream handler not installed")

        # Aliases
        if "alias" in doc:
            aliases = doc["alias"]
            for alias in aliases:
                if alias != "":
                    db.add_alias(show_id, alias)
            logger.info(
                "Added %d alias%s", len(aliases), "es" if len(aliases) > 1 else ""
            )

    return True
