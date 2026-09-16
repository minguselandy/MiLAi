from __future__ import annotations

from milai.config.settings import load_settings
from milai.persistence.database import Database


def main() -> None:
    settings = load_settings()
    database = Database(settings, expected_role="milai_api")
    try:
        database.ping()
        print("canonical database: ready")
    finally:
        database.close()
