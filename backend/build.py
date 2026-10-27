"""Build the bundled SQLite database: ``data/opscore.db`` with the four sample clients.

Vercel runs this during the build (see ``[tool.vercel.scripts]`` in pyproject.toml), so
the deployment ships a ready database and needs no database service. See app/bundled_db.py.

    python build.py
"""

import time

from app.bundled_db import BUNDLED, build

if __name__ == "__main__":
    started = time.perf_counter()
    BUNDLED.unlink(missing_ok=True)
    build(BUNDLED)
    print(f"Built {BUNDLED} in {time.perf_counter() - started:.1f} s.")
