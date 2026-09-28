Katsina Zonal FileTrack - Render PostgreSQL Update

This version keeps SQLite for local use when DATABASE_URL is absent, and automatically uses PostgreSQL on Render when DATABASE_URL is set.

Render settings:
Build: pip install -r requirements.txt
Start: gunicorn app:app
Environment: FILETRACK_SECRET (strong secret), DATABASE_URL (Render Postgres Internal Database URL)

IMPORTANT: The existing local filetrack.db is not automatically copied into PostgreSQL. Use migrate_sqlite_to_postgres.py from the original project on a machine that can reach the Render database.
