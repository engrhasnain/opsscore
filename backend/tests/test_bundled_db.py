"""The bundled SQLite database used when hosting with no database service (Vercel)."""

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# Runs in a fresh interpreter, so the application's settings are read as on Vercel.
SCRIPT = """
import json
from fastapi.testclient import TestClient
from app.main import app
from app.bundled_db import runtime_path
from app.demo_seed import DEMO_PASSWORD

client = TestClient(app, raise_server_exceptions=False)
login = client.post("/api/v1/auth/login", json={"email": "owner@permian.demo", "password": DEMO_PASSWORD})
print(json.dumps({"path": str(runtime_path()), "exists": runtime_path().exists(),
                  "ready": client.get("/health/ready").status_code, "login": login.status_code}))
"""


def _run(tmp_path: Path, **extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPSCORE_") and k not in ("DATABASE_URL", "VERCEL")}
    env.update({"VERCEL": "1", "TMP": str(tmp_path), "TEMP": str(tmp_path), "TMPDIR": str(tmp_path), **extra})
    out = subprocess.run(  # noqa: S603  (our own interpreter and script)
        [sys.executable, "-c", SCRIPT], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300, check=True
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_hosted_without_a_database_runs_on_a_temporary_copy(tmp_path):
    result = _run(tmp_path)
    assert result["exists"]
    assert Path(result["path"]).is_relative_to(tmp_path)
    assert result["ready"] == 200
    assert result["login"] == 200


def test_a_configured_database_is_used_instead(tmp_path):
    own = tmp_path / "own.db"
    result = _run(tmp_path, OPSCORE_DATABASE_URL=f"sqlite:///{own.as_posix()}")
    assert not result["exists"]
    assert result["login"] != 200  # an empty database: no sample clients were loaded
