from __future__ import annotations

import atexit

from waitress import serve

from milai.api import create_app
from milai.config.settings import load_settings, prepare_runtime_directories
from milai.observability import configure_logging
from milai.persistence import Database


def main() -> None:
    settings = load_settings()
    prepare_runtime_directories(settings)
    configure_logging(settings.log_level, settings.log_format)
    database = Database(settings, expected_role="milai_api")
    steward_database = Database(
        settings,
        dsn=settings.steward_database_dsn,
        expected_role="milai_steward",
    )
    atexit.register(database.close)
    atexit.register(steward_database.close)
    app = create_app(settings, database=database, steward_database=steward_database)
    serve(
        app,
        host=settings.bind_host,
        port=settings.bind_port,
        threads=settings.api_threads,
        clear_untrusted_proxy_headers=True,
    )
