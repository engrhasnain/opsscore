"""Prepare the database during the Vercel build (see ``[tool.vercel.scripts]`` in pyproject.toml).

- With a database configured (``DATABASE_URL``, e.g. Neon connected in Vercel): apply the
  migrations and load the four sample clients if they are not there yet. Every server
  instance then shares that one database.
- Without one: build ``data/opscore.db`` with the tables and the sample clients, which the
  deployment ships and each instance copies (app/bundled_db.py).

    python build.py
"""

import os
import time

from app.bundled_db import BUNDLED, build
from app.config import DATABASE_ENV

if __name__ == "__main__":
    started = time.perf_counter()
    if any(os.getenv(name) for name in DATABASE_ENV):
        from app import cli

        cli.migrate()
        cli.seed_demo()
        print(f"Database ready in {time.perf_counter() - started:.1f} s.")
    else:
        BUNDLED.unlink(missing_ok=True)
        build(BUNDLED)
        print(f"Built {BUNDLED} in {time.perf_counter() - started:.1f} s.")
