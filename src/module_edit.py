import logging
from typing import Any

import yaml

from data.database import DatabaseDatabase
from data.models import UnprocessedShow, UnprocessedStream, str_to_showtype
from services import AbstractInfoHandler, AbstractServiceHandler, Handlers

logger = logging.getLogger(__name__)


def main(db: DatabaseDatabase, edit_file: str, handlers: Handlers) -> None:
    if not edit_file:
        logger.warning("Missing edit file")
        return
    logger.info('Parsing show edit file "%s"', edit_file)
    try:
        with open(edit_file, "r", encoding="UTF-8") as f:
            parsed: list[dict[str, Any]] = list(yaml.full_load_all(f))
    except yaml.YAMLError:
        logger.exception("Failed to parse edit file")
        return
    logger.debug("  num shows=%d", len(parsed))
    try:
        for entry in parsed:
            _parse_entry(db=db, handlers=handlers, entry=entry)
    except Exception:
        logger.error("Edit failed; reverting")
        db.rollback()
    else:
        logger.info("Edit successful; saving")
        db.commit()


def _parse_entry(
    db: DatabaseDatabase, handlers: Handlers, entry: dict[str, Any]
) -> None:
    # Add show to the database
    show_id = _process_show(db=db, entry=entry)

    # Add links to database sites to the database
    infos: dict[str, str] = entry.get("info", {})
    for info_key, url in infos.items():
        if not url:
            continue
        _process_info(
            db=db,
            info_handlers=handlers.infos,
            show_id=show_id,
            site_key=info_key,
            url=url,
        )

    # Add stream information to the database
    streams: dict[str, str] = entry.get("streams", {})
    for service_key, url in streams.items():
        if not url:
            continue
        _process_stream(
            db=db,
            service_handlers=handlers.streams,
            show_id=show_id,
            service_key=service_key,
            url=url,
        )

    # Add aliases to the database
    aliases: list[str] = entry.get("alias", [])
    _process_aliases(db=db, show_id=show_id, aliases=aliases)


def _process_show(db: DatabaseDatabase, entry: dict[str, Any]) -> int:
    name = entry["title"]
    name_en = entry.get("title_en", "")
    stype = str_to_showtype(entry.get("type", "tv"))
    length = entry.get("length", 0)
    has_source = entry.get("has_source", False)
    is_nsfw = entry.get("is_nsfw", False)
    logger.info('Adding show "%s" (%s)', name, stype)
    logger.debug("  has_source=%s", has_source)
    logger.debug("  is_nsfw=%s", is_nsfw)
    show = UnprocessedShow(
        name=name,
        name_en=name_en,
        show_type=stype,
        episode_count=length,
        has_source=has_source,
        is_nsfw=is_nsfw,
    )
    show_id = db.search_show_id_by_name(name)
    if show_id:
        db.update_show(show_id, show, commit=False)
    else:
        show_id = db.add_show(show, commit=False)
    return show_id


def _process_info(
    db: DatabaseDatabase,
    info_handlers: dict[str, AbstractInfoHandler],
    show_id: int,
    site_key: str,
    url: str,
) -> None:
    logger.debug("  Info %s: %s", site_key, url)
    info_handler = info_handlers[site_key]
    if not info_handler:
        logger.error("    Info handler not installed")
        return
    show_key = info_handler.extract_show_id(url)
    if not show_key:
        logger.warning("    Could not extract show id")
        return
    logger.debug("    id=%s", show_key)
    db.add_link_(show_id=show_id, show_key=show_key, site_key=site_key)


def _extract_offset(url: str) -> tuple[str, int]:
    remote_offset = 0
    roi = url.rfind("|")
    if 0 < roi < len(url) - 1:
        remote_offset = int(url[roi + 1 :])
        url = url[:roi]
    return url, remote_offset


def _process_stream(
    db: DatabaseDatabase,
    service_handlers: dict[str, AbstractServiceHandler],
    show_id: int,
    service_key: str,
    url: str,
) -> None:
    try:
        url, remote_offset = _extract_offset(url)
    except Exception:
        logger.exception('Improperly formatted stream URL "%s"', url)
        return
    logger.info("  Stream %s: %s", service_key, url)

    stream_key = service_key.split("|")[0]
    stream_handler = service_handlers.get(stream_key, None)
    if stream_handler:
        show_key = stream_handler.extract_show_key(url) or ""
        logger.debug("    id=%s", show_key)
        service_id = db.search_service_id_by_key(key=service_key)
        s = UnprocessedStream(show_key=show_key, remote_offset=remote_offset)
        db.add_stream_(s, service_id=service_id, show_id=show_id, commit=False)
    elif "|" in service_key:
        # Lite stream
        service, service_name = service_key.split("|", maxsplit=1)
        db.add_lite_stream(show_id, service, service_name, url)
    else:
        logger.error("    Stream handler not installed")


def _process_aliases(db: DatabaseDatabase, show_id: int, aliases: list[str]) -> None:
    aliases = list(filter(None, aliases))
    db.add_aliases(show_id=show_id, *aliases)
    logger.info("Added %d alias%s", len(aliases), "" if len(aliases) == 1 else "es")
