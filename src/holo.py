#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from dataclasses import dataclass
import argparse
import logging
from logging.handlers import TimedRotatingFileHandler
from time import time
from typing import Type
from data import database
from config import Config, InvalidConfigException
import services

if sys.version_info[0] != 3 or sys.version_info[1] < 10:
	print("Holo requires Python version 3.10 or greater")
	sys.exit(1)

# Metadata
NAME = "Holo"
DESCRIPTION = "episode discussion bot"
VERSION = "0.1.4"


@dataclass
class ParserArguments:
	config_file: str
	module: str
	debug: bool
	log_dir: str
	db_name: str | None
	subreddit: str | None
	no_input: bool
	extra: list[str]
	output: str


# Do the things
def main(config: Config, args: Type[ParserArguments]) -> None:

	# Set things up
	db = database.living_in(config.database)
	if not db:
		logging.error("Cannot continue running without a database")
		return

	services.setup_services(config)

	# Run the requested module
	try:
		logging.debug("Running module %s", config.module)
		if config.module == "setup":
			logging.info("Setting up database")
			db.setup_tables()
			logging.info("Registering services")
			db.register_services(services.get_service_handlers())
			db.register_link_sites(services.get_link_handlers())
			db.register_poll_sites(services.get_poll_handlers())
		elif config.module == "edit":
			logging.info("Editing database")
			import module_edit as m

			m.main(db=db, edit_file=args.extra[0])
		elif config.module == "episode":
			logging.info("Finding new episodes")
			import module_find_episodes as m

			m.main(config=config, db=db)
		elif config.module == "find":
			logging.info("Finding new shows")
			import module_find_shows as m

			if args.output == "db":
				m.main(config=config, db=db)
			elif args.output == "yaml":
				file_name = args.extra[0] if args.extra else "find_output.yaml"
				m.main(config=config, db=db, output_file=file_name)
		elif config.module == "update":
			logging.info("Updating shows")
			import module_update_shows as m

			m.main(config=config, db=db)
		elif config.module == "create":
			logging.info("Creating new thread")
			import module_create_threads as m

			m.main(config=config, db=db, show_name=args.extra[0], episode=args.extra[1])
		elif config.module == "batch":
			logging.info("Batch creating threads")
			import module_batch_create as m

			m.main(
				config=config,
				db=db,
				show_name=args.extra[0],
				episode_count=args.extra[1],
			)
		else:
			logging.warning("This should never happen or you broke it!")
	except Exception as e:
		logging.exception("Unknown exception or error: %s", e)
		db.rollback()

	db.close()


if __name__ == "__main__":
	# Ensure proper files can be access if running with cron
	os.chdir(str(Path(__file__).parent.parent))

	# Parse args
	parser = argparse.ArgumentParser(description=f"{NAME}, {DESCRIPTION}")
	parser.add_argument(
		"--no-input",
		dest="no_input",
		action="store_true",
		help="run without stdin and write to a log file",
	)
	parser.add_argument(
		"-m",
		"--module",
		dest="module",
		choices=["setup", "edit", "episode", "update", "find", "create", "batch"],
		default="episode",
		help="runs the specified module",
	)
	parser.add_argument(
		"-c",
		"--config",
		dest="config_file",
		default="config.ini",
		help="use or create the specified database location",
	)
	parser.add_argument(
		"-d",
		"--database",
		dest="db_name",
		default=None,
		help="use or create the specified database location",
	)
	parser.add_argument(
		"-s",
		"--subreddit",
		dest="subreddit",
		default=None,
		help="set the subreddit on which to make posts",
	)
	parser.add_argument(
		"-o",
		"--output",
		dest="output",
		default="db",
		help="set the output mode (db or yaml) if supported",
	)
	parser.add_argument(
		"-L",
		"--log-dir",
		dest="log_dir",
		default="logs",
		help="set the log directory",
	)
	parser.add_argument(
		"-v",
		"--version",
		action="version",
		version=f"{NAME} v{VERSION}, {DESCRIPTION}",
	)
	parser.add_argument("--debug", action="store_true", default=False)
	parser.add_argument("extra", nargs="*")
	args = parser.parse_args(namespace=ParserArguments)

	# Load config file
	config_file = (
		os.environ["HOLO_CONFIG"] if "HOLO_CONFIG" in os.environ else args.config_file
	)
	try:
		config = Config.from_file(config_file)
	except InvalidConfigException:
		print("Cannot start without a valid configuration file")
		sys.exit(2)

	# Override config with args
	config.debug |= args.debug
	config.module = args.module
	config.log_dir = args.log_dir
	if args.db_name is not None:
		config.database = args.db_name
	if args.subreddit is not None:
		config.subreddit = args.subreddit

	# Start
	use_log = args.no_input
	if use_log:
		os.makedirs(config.log_dir, exist_ok=True)

		log_file = f"{config.log_dir}/holo_{config.module}.log"
		logging.basicConfig(
			handlers=[
				TimedRotatingFileHandler(
					log_file, when="midnight", backupCount=7, encoding="UTF-8"
				)
			],
			format="%(asctime)s | %(module)s | %(levelname)s | %(message)s",
			datefmt="%Y-%m-%d %H:%M:%S",
			level=logging.DEBUG if config.debug else logging.INFO,
		)
	else:
		logging.basicConfig(
			format="%(levelname)s | %(message)s",
			level=logging.DEBUG if config.debug else logging.INFO,
		)
	logging.getLogger("requests").setLevel(logging.WARNING)
	logging.getLogger("praw-script-oauth").setLevel(logging.WARNING)

	if use_log:
		logging.info("-" * 60)

	if not config.is_valid:
		logging.warning("Configuration state invalid")

	if config.debug:
		logging.info("DEBUG MODE ENABLED")

	start_time = time()
	main(config=config, args=args)
	end_time = time()

	time_diff = end_time - start_time
	logging.info("")
	logging.info("Run time: %.6f seconds", time_diff)

	if use_log:
		logging.info("%s%s", "-" * 60, "\n")
