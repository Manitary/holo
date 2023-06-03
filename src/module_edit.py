import logging
from typing import Any

import yaml

import services
from data.database import DatabaseDatabase
from data.models import ShowType, UnprocessedShow, UnprocessedStream, str_to_showtype

logger = logging.getLogger(__name__)


class MalformedYAMLError(yaml.YAMLError):
	"""Raised when the data in the YAML file is not formatted correctly."""


class InaccurateYAMLError(yaml.YAMLError):
	"""Raised when the data in the YAML file results in issues with the database."""


def main(db: DatabaseDatabase, edit_file: str) -> None:
	if not edit_file:
		logger.warning("Nothing to do")
	if _edit_with_file(db=db, edit_file=edit_file):
		logger.info("Edit successful; saving")
		db.commit()
	else:
		logger.error("Edit failed; reverting")
		db.rollback()


def _edit_with_file(db: DatabaseDatabase, edit_file: str) -> bool:

	logger.info('Parsing show edit file "%s"', edit_file)
	try:
		with open(edit_file, "r", encoding="UTF-8") as f:
			parsed: list[dict[str, Any]] = list(yaml.full_load_all(f))
	except yaml.YAMLError:
		logger.exception("Failed to parse edit file")
		return False

	logger.debug("  num shows=%s", len(parsed))

	for doc in parsed:
		try:
			show = get_show_from(doc)
			show_id = update_db_with_show(db=db, show=show)
		except yaml.YAMLError:
			return False

		# Info
		infos: dict[str, str] = doc.get("info", {})
		process_show_info(db=db, show=show, show_id=show_id, infos=infos)

		# Streams
		streams: dict[str, str] = doc.get("streams", {})
		process_show_streams(db=db, show_id=show_id, streams=streams)

		# Aliases
		aliases: list[str] = doc.get("alias", [])
		process_show_aliases(db=db, show_id=show_id, aliases=aliases)

	return True


def get_show_from(doc: dict[str, Any]) -> UnprocessedShow:
	name: str = doc["title"]
	name_en: str = doc.get("title_en", "")
	stype: ShowType = str_to_showtype(doc.get("type", "tv"))
	length: int = doc.get("length", 0)
	has_source: bool = doc.get("has_source", False)
	is_nsfw: bool = doc.get("is_nsfw", False)

	logger.info('Adding show "%s" (%s)', name, stype)
	logger.debug("  has_source=%s", has_source)
	logger.debug("  is_nsfw=%s", is_nsfw)
	if stype == ShowType.UNKNOWN:
		logger.error('Invalid show type "%s"', stype)
		raise MalformedYAMLError()

	show = UnprocessedShow(
		site_key="",
		show_key="",
		name=name,
		name_en=name_en,
		more_names=[],
		show_type=stype,
		episode_count=length,
		has_source=1 if has_source else 0,
		is_nsfw=1 if is_nsfw else 0,
	)
	return show


def update_db_with_show(db: DatabaseDatabase, show: UnprocessedShow) -> int:
	found_ids = db.search_show_ids_by_names(show.name, exact=True)
	logger.debug("Found ids: %s", found_ids)
	if len(found_ids) == 0:
		show_id = db.add_show(show, commit=False)
		if not show_id:
			raise InaccurateYAMLError()
		return show_id
	if len(found_ids) == 1:
		show_id = found_ids.pop()
		db.update_show(show_id, show, commit=False)
		return show_id
	logger.error("More than one ID found for show")
	raise InaccurateYAMLError


def process_show_info(
	db: DatabaseDatabase, show: UnprocessedShow, show_id: int, infos: dict[str, str]
) -> None:
	for info_key, url in infos.items():
		if not url:
			continue
		logger.debug("  Info %s: %s", info_key, url)
		info_handler = services.get_link_handler(key=info_key)
		if not info_handler:
			logger.error("    Info handler not installed")
			continue
		info_id = info_handler.extract_show_id(url)
		if not info_id:
			logger.error("    Unable to extract show id")
			continue
		logger.debug("    id=%s", info_id)
		if not db.has_link(site_key=info_key, key=info_id, show=show_id):
			show.site_key = info_key
			show.show_key = info_id
			db.add_link(raw_show=show, show_id=show_id, commit=False)


def process_remote_offset(url: str) -> tuple[str, int]:
	roi = url.rfind("|")
	if roi == -1:
		return url, 0
	return url[:roi], int(url[roi + 1 :])


def process_show_streams(
	db: DatabaseDatabase, show_id: int, streams: dict[str, str]
) -> None:
	for service_key, url in streams.items():
		if not url:
			continue
		try:
			url, remote_offset = process_remote_offset(url)
		except ValueError:
			logger.exception('Improperly formatted stream URL "%s"', url)
			continue
		logger.info("  Stream %s: %s", service_key, url)

		service_id = service_key.split("|")[0]
		stream_handler = services.get_service_handler(key=service_id)
		if stream_handler:
			show_key = stream_handler.extract_show_key(url)
			if not show_key:
				logger.error("    Unable to extract show key")
				continue
			logger.debug("    id=%s", show_key)

			if not db.has_stream(service_id, show_key):
				s = UnprocessedStream(
					service_key=service_id,
					show_key=show_key,
					show_id=None,
					name="",
					remote_offset=remote_offset,
				)
				db.add_stream(s, show_id, commit=False)
			else:
				service = db.get_service(key=service_id)
				s = db.get_stream(service_tuple=(service, show_key))
				db.update_stream(
					stream=s, show=show_id, remote_offset=remote_offset, commit=False
				)
		elif "|" in service_key:
			# Lite stream
			service, service_name = service_key.split("|", maxsplit=1)
			db.add_lite_stream(
				show=show_id, service=service, service_name=service_name, url=url
			)
		else:
			logger.error("    Stream handler not installed")


def process_show_aliases(
	db: DatabaseDatabase, show_id: int, aliases: list[str]
) -> None:
	for alias in aliases:
		if alias:
			db.add_alias(show_id=show_id, alias=alias)
	logger.info("Added %s alias%s", len(aliases), "es" if len(aliases) > 1 else "")
