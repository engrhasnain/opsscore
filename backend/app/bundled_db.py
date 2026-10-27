"""A ready-made SQLite database for hosting without a database service (Vercel).

``python build.py`` creates ``data/opscore.db`` with the tables and the four sample
clients, and the deployment ships it. The deployed code is read-only and only the
temporary folder is writable, so each server instance copies that file there when it
starts. What happens during a session lasts while that instance runs; a new instance
starts again from the clean copy.

Setting a database URL (``OPSCORE_DATABASE_URL`` or ``DATABASE_URL``, e.g. Neon on
Vercel) switches this off and the application uses that database instead.
"""

import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
BUNDLED = BACKEND_DIR / "data" / "opscore.db"

logger = logging.getLogger("opscore.bundled_db")
_lock = threading.Lock()


def runtime_path() -> Path:
    return Path(tempfile.gettempdir()) / "opscore" / "opscore.db"


def build(target: Path) -> None:
    """Create a fresh database at ``target`` with the tables and the sample clients."""
    from app import cli
    from app.config import get_settings
    from app.db import configure, get_engine

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".building")
    partial.unlink(missing_ok=True)
    os.environ["OPSCORE_DATABASE_URL"] = f"sqlite:///{partial.as_posix()}"
    get_settings.cache_clear()
    configure(_engine_for(partial))
    try:
        cli.migrate()
        cli.seed_demo()
    finally:
        get_engine().dispose()
    os.replace(partial, target)


def _engine_for(path: Path):
    from app.db import build_engine

    return build_engine(f"sqlite:///{path.as_posix()}")


def use_if_hosted() -> None:
    """On Vercel with no database configured, point the application at its own copy."""
    if not os.getenv("VERCEL") or os.getenv("OPSCORE_DATABASE_URL") or os.getenv("DATABASE_URL"):
        return
    target = runtime_path()
    with _lock:
        if not target.exists():
            if BUNDLED.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                partial = target.with_suffix(".copying")
                shutil.copyfile(BUNDLED, partial)
                os.replace(partial, target)
                logger.info("copied the bundled database", extra={"path": str(target)})
            else:
                logger.warning("no bundled database shipped; building one", extra={"path": str(target)})
                build(target)
    from app.config import get_settings
    from app.db import configure

    os.environ["OPSCORE_DATABASE_URL"] = f"sqlite:///{target.as_posix()}"
    get_settings.cache_clear()
    configure(_engine_for(target))
