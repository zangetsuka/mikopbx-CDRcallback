from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from .config import AppConfig
from .logging_utils import setup_logging
from .service import ServiceContainer
from .web import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified MikoPBX service")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("serve", help="Start the unified web service")
    subparsers.add_parser("collect-once", help="Run a single collection pass")

    stats_parser = subparsers.add_parser("stats", help="Print call statistics")
    stats_parser.add_argument("--days", type=int, default=7, help="Stats window in days")

    return parser


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "serve"

    config = AppConfig.from_env()
    config.ensure_directories()
    setup_logging(config.logging)
    logger = logging.getLogger("mikoapi")
    services = ServiceContainer(config)

    try:
        if command == "collect-once":
            saved = services.collector.collect_calls(limit=config.collector.batch_limit)
            _print_json(
                {
                    "saved": saved,
                    "total_in_db": services.db.get_total_count(),
                }
            )
            return

        if command == "stats":
            _print_json(
                {
                    "calls": services.db.get_statistics(days=args.days),
                    "daily": services.db.get_daily_stats(days=args.days),
                    "callback": services.db.get_callback_statistics(days=args.days),
                }
            )
            return

        services.start_background_workers()
        app = create_app(config, services)

        logger.info(
            "Starting unified service on http://%s:%s",
            config.web.host,
            config.web.port,
        )
        app.run(
            host=config.web.host,
            port=config.web.port,
            debug=config.web.debug,
            use_reloader=False,
            threaded=True,
        )
    finally:
        services.stop_background_workers()


if __name__ == "__main__":
    main()
