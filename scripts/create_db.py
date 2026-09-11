"""Create the Tech Atlas database: the sources collection and its indexes.

This also runs automatically on app start-up (app.bootstrap); keep the script
for manual use. Run from the project root with the venv active:
    python scripts/create_db.py
Idempotent — safe to run again.
"""

from app.services.db.bootstrap import ensure_database
from app.services.db.mongo import get_db, ping
from app.settings import get_settings


def main() -> None:
    ping()
    ensure_database()
    print(f"database {get_settings().mongo_db!r} ready — collections: {get_db().list_collection_names()}")


if __name__ == "__main__":
    main()
