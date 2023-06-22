#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from time import time
from typing import Type

import config as config_loader
import services
from data import database

logger = logging.getLogger(__name__)

if sys.version_info[0] != 3 or sys.version_info[1] < 5:
    print("Holo requires Python version 3.5 or greater")
    sys.exit(1)

# Metadata
name = "Holo"
description = "episode discussion bot"
version = "0.1.4"

# Ensure proper files can be access if running with cron
os.chdir(str(Path(__file__).parent.parent))


# Do the things


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


def main(config: config_loader.Config, args: Type[ParserArguments]) -> None:
    # Set things up
    db = database.living_in(config.database)
    if not db:
        logger.error("Cannot continue running without a database")
        return

    services.setup_services(config)

    # Run the requested module
    try:
        logger.debug("Running module %s", config.module)
        if config.module == "setup":
            logger.info("Setting up database")
            db.setup_tables()
            logger.info("Registering services")
            db.register_services(services.get_service_handlers())
            db.register_link_sites(services.get_link_handlers())
            db.register_poll_sites(services.get_poll_handlers())
        elif config.module == "edit":
            logger.info("Editing database")
            import module_edit as m

            m.main(config=config, db=db, edit_file=args.extra[0])
        elif config.module == "episode":
            logger.info("Finding new episodes")
            import module_find_episodes as m

            m.main(config, db)
        elif config.module == "find":
            logger.info("Finding new shows")
            import module_find_shows as m

            if args.output[0] == "db":
                m.main(config=config, db=db, output_yaml=False)
            elif args.output[0] == "yaml":
                f = args.extra[0] if len(args.extra) > 0 else "find_output.yaml"
                m.main(config=config, db=db, output_yaml=True, output_file=f)
        elif config.module == "update":
            logger.info("Updating shows")
            import module_update_shows as m

            m.main(config=config, db=db)
        elif config.module == "create":
            logger.info("Creating new thread")
            import module_create_threads as m

            m.main(config=config, db=db, show_name=args.extra[0], episode=args.extra[1])
        elif config.module == "batch":
            logger.info("Batch creating threads")
            import module_batch_create as m

            m.main(
                config=config,
                db=db,
                show_name=args.extra[0],
                episode_count=args.extra[1],
            )
        else:
            logger.warning("This should never happen or you broke it!")
    except Exception:
        logger.exception("Unknown exception or error")
        db.rollback()

    db.close()


if __name__ == "__main__":
    # Parse args
    parser = argparse.ArgumentParser(description=f"{name}, {description}")
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
        nargs=1,
        choices=["setup", "edit", "episode", "update", "find", "create", "batch"],
        default=["episode"],
        help="runs the specified module",
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config_file",
        nargs=1,
        default=["config.ini"],
        help="use or create the specified database location",
    )
    parser.add_argument(
        "-d",
        "--database",
        dest="db_name",
        nargs=1,
        default=None,
        help="use or create the specified database location",
    )
    parser.add_argument(
        "-s",
        "--subreddit",
        dest="subreddit",
        nargs=1,
        default=None,
        help="set the subreddit on which to make posts",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        nargs=1,
        default="db",
        help="set the output mode (db or yaml) if supported",
    )
    parser.add_argument(
        "-L",
        "--log-dir",
        dest="log_dir",
        nargs=1,
        default=["logs"],
        help="set the log directory",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"{name} v{version}, {description}",
    )
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument("extra", nargs="*")
    args = parser.parse_args(namespace=ParserArguments)

    # Load config file
    config_file = (
        os.environ["HOLO_CONFIG"]
        if "HOLO_CONFIG" in os.environ
        else args.config_file[0]
    )
    c = config_loader.from_file(config_file)
    if c is None:
        print("Cannot start without a valid configuration file")
        sys.exit(2)

    # Override config with args
    c.debug |= args.debug
    c.module = args.module[0]
    c.log_dir = args.log_dir[0]
    if args.db_name is not None:
        c.database = args.db_name[0]
    if args.subreddit is not None:
        c.subreddit = args.subreddit[0]

    # Start
    use_log = args.no_input
    if use_log:
        os.makedirs(c.log_dir, exist_ok=True)

        # from datetime import datetime
        # log_file = "logs/{date}_{mod}.log".format(date=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), mod=c.module)
        log_file = f"{c.log_dir}/holo_{c.module}.log"
        logging.basicConfig(
            # filename=log_file,
            handlers=[
                TimedRotatingFileHandler(
                    log_file, when="midnight", backupCount=7, encoding="UTF-8"
                )
            ],
            format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            level=logging.DEBUG if c.debug else logging.INFO,
        )
    else:
        logging.basicConfig(
            format="%(levelname)s | %(message)s",
            level=logging.DEBUG if c.debug else logging.INFO,
        )
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("praw-script-oauth").setLevel(logging.WARNING)

    if use_log:
        logger.info("------------------------------------------------------------")
    err = config_loader.validate(c)
    if err:
        logger.warning("Configuration state invalid: %s", err)

    if c.debug:
        logger.info("DEBUG MODE ENABLED")
    start_time = time()
    main(config=c, args=args)
    end_time = time()

    time_diff = end_time - start_time
    logger.info("")
    logger.info("Run time: %.6f seconds", time_diff)

    if use_log:
        logger.info("------------------------------------------------------------\n")
