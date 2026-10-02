"""
Local prototype mode (Stage 1): data directory, safe startup migration,
frontend serving, cookies and the launcher.

Each scenario runs in a subprocess because mode and paths are decided
when the application is first imported. Nothing here touches the shared
test database: every scenario gets its own temporary data directory.
Windows is not exercised; the Windows default path is only simulated.
"""

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

PASSWORD = "local-test-password"

DRIVER = r"""
import json, sys
from fastapi.testclient import TestClient
from backend.app.main import app
out = {}
H = {"X-Requested-With": "fetch"}
with TestClient(app) as c:
    out["health"] = [c.get("/api/health").status_code, c.get("/api/health").json()]
    r = c.get("/")
    out["root"] = [r.status_code, r.headers["content-type"].split(";")[0], "FAKE-INDEX" in r.text]
    r = c.get("/some/client/route")
    out["spa"] = [r.status_code, "FAKE-INDEX" in r.text]
    r = c.get("/assets/app.js")
    out["asset"] = [r.status_code, r.headers["cache-control"]]
    out["missing_asset"] = c.get("/assets/old.js").status_code
    r = c.get("/api/does-not-exist")
    out["api_404"] = [r.status_code, r.headers["content-type"].split(";")[0]]
    out["api_post_404"] = c.post("/api/does-not-exist", headers=H).status_code
    out["traversal"] = c.get("/..%2f..%2fsecret.txt").status_code
    out["anon_api"] = c.get("/api/batches").status_code
    r = c.post("/api/auth/login", headers=H, json={"email": "admin@local.test", "password": sys.argv[1]})
    cookie = r.headers.get("set-cookie", "")
    out["login"] = r.status_code
    out["cookie"] = {"httponly": "HttpOnly" in cookie, "secure": "Secure" in cookie,
                     "samesite": "samesite=lax" in cookie.lower()}
    out["authed_api"] = c.get("/api/batches").status_code
    out["no_csrf_header"] = c.post("/api/auth/logout").status_code
    out["logout"] = c.post("/api/auth/logout", headers=H).status_code
    out["after_logout"] = c.get("/api/batches").status_code
print("RESULT " + json.dumps(out))
"""


@pytest.fixture
def dist(tmp_path):
    folder = tmp_path / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text("<html>FAKE-INDEX</html>")
    (folder / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("secret")
    return folder


def env_for(data_dir, dist=None, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("COACHING_")}
    env.update(
        COACHING_APP_MODE="local",
        COACHING_DATA_DIR=str(data_dir),
        PYTHONDONTWRITEBYTECODE="1",
    )
    if dist is not None:
        env["COACHING_FRONTEND_DIST"] = str(dist)
    env.update(extra)
    return env


def run(args, env, input_text=None):
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
        input=input_text, timeout=120,
    )


UPGRADE_OLD = (
    "from alembic import command; from alembic.config import Config; "
    "c = Config('alembic.ini'); c.attributes['configure_logger'] = False; "
    "command.upgrade(c, '0002')"
)


def migrate(env):
    return run(["scripts/run_local.py", "--migrate-only"], env)


def create_admin(env):
    return run(
        ["scripts/manage.py", "create-institute", "--name", "Local Test Institute",
         "--admin-name", "Admin", "--admin-email", "admin@local.test",
         "--password-stdin"],
        env, input_text=PASSWORD + "\n",
    )


def drive(env):
    result = run(["-c", DRIVER, PASSWORD], env)
    assert result.returncode == 0, result.stderr
    line = next(l for l in result.stdout.splitlines() if l.startswith("RESULT "))
    return json.loads(line[len("RESULT "):])


def db_file(data_dir):
    return Path(data_dir) / "data" / "coaching.db"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def table_count(path, table):
    connection = sqlite3.connect(path)
    try:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        connection.close()


# ---------------------------------------------------------------- config

CONFIG_PROBE = (
    "import json; from backend.app import config as c; "
    "print(json.dumps({'mode': c.APP_MODE, 'data': str(c.DATA_DIR), "
    "'db': str(c.DATABASE_PATH), 'backup': c.BACKUP_DIR, "
    "'serve': c.SERVE_FRONTEND, 'migrate': c.AUTO_MIGRATE, "
    "'secure': c.COOKIE_SECURE, 'docs': c.API_DOCS_ENABLED, "
    "'host': c.HOST, 'port': c.PORT}))"
)


def probe(env, prelude=""):
    result = run(["-c", prelude + CONFIG_PROBE], env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_development_defaults_are_unchanged(tmp_path):
    env = env_for(tmp_path)
    for name in ("COACHING_APP_MODE", "COACHING_DATA_DIR"):
        env.pop(name)
    values = probe(env)
    assert values["mode"] == "development"
    assert values["db"] == str(PROJECT_ROOT / "data" / "coaching.db")
    assert not values["serve"] and not values["migrate"] and values["docs"]
    assert values["host"] == "127.0.0.1" and values["port"] == 8000


def test_local_mode_paths_come_from_the_data_dir(tmp_path):
    values = probe(env_for(tmp_path / "home"))
    assert values["db"] == str(tmp_path / "home" / "data" / "coaching.db")
    assert values["backup"] == str(tmp_path / "home" / "backups")
    assert values["serve"] and values["migrate"]
    assert not values["secure"] and not values["docs"]


def test_explicit_db_and_backup_override_the_data_dir(tmp_path):
    env = env_for(
        tmp_path / "home",
        COACHING_DB_PATH=str(tmp_path / "x" / "other.db"),
        COACHING_BACKUP_DIR=str(tmp_path / "bk"),
    )
    values = probe(env)
    assert values["db"] == str(tmp_path / "x" / "other.db")
    assert values["backup"] == str(tmp_path / "bk")


def test_windows_default_location_is_simulated(tmp_path):
    # SIMULATION ONLY: pretends to be Windows to check the path rule.
    env = env_for(tmp_path)
    env.pop("COACHING_DATA_DIR")
    env["LOCALAPPDATA"] = str(tmp_path / "LocalAppData")
    values = probe(env, "import sys; sys.platform = 'win32'; ")
    assert values["data"] == str(tmp_path / "LocalAppData" / "CoachingIntel")


def test_linux_default_location_is_user_data_dir(tmp_path):
    env = env_for(tmp_path)
    env.pop("COACHING_DATA_DIR")
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg")
    assert probe(env)["data"] == str(tmp_path / "xdg" / "CoachingIntel")


def test_unknown_mode_and_bad_port_are_refused(tmp_path):
    bad_mode = run(["-c", "import backend.app.config"], env_for(tmp_path, COACHING_APP_MODE="prod"))
    assert bad_mode.returncode != 0 and "Unknown application mode" in bad_mode.stderr
    bad_port = run(["-c", "import backend.app.config"], env_for(tmp_path, COACHING_PORT="99999"))
    assert bad_port.returncode != 0 and "COACHING_PORT" in bad_port.stderr


def test_production_is_still_strict(tmp_path):
    values = probe(env_for(tmp_path, COACHING_APP_MODE="production"))
    assert values["secure"] and not values["docs"]
    assert not values["serve"] and not values["migrate"]


# --------------------------------------------------- fresh start and use

def test_fresh_data_dir_end_to_end(tmp_path, dist):
    home = tmp_path / "home"
    env = env_for(home, dist)

    first = migrate(env)
    assert first.returncode == 0, first.stderr
    assert "created" in first.stdout
    for name in ("data", "backups", "uploads", "logs", "exports", "config"):
        assert (home / name).is_dir()
    assert db_file(home).exists()

    assert create_admin(env).returncode == 0

    out = drive(env)
    assert out["health"][0] == 200
    assert out["health"][1]["schema_revision"] == out["health"][1]["expected_revision"]
    assert out["root"] == [200, "text/html", True]
    assert out["spa"] == [200, True]
    assert out["asset"][0] == 200 and "immutable" in out["asset"][1]
    assert out["missing_asset"] == 404
    assert out["api_404"] == [404, "application/json"]
    assert out["api_post_404"] == 404
    assert out["traversal"] in (404, 400)
    assert out["anon_api"] == 401
    assert out["login"] == 200
    assert out["cookie"] == {"httponly": True, "secure": False, "samesite": True}
    assert out["authed_api"] == 200
    assert out["no_csrf_header"] == 403
    assert out["logout"] == 200
    assert out["after_logout"] == 401


def test_restart_preserves_data_and_makes_no_backup(tmp_path, dist):
    home = tmp_path / "home"
    env = env_for(home, dist)
    assert migrate(env).returncode == 0
    assert create_admin(env).returncode == 0
    before = table_count(db_file(home), "users")

    for _ in range(2):
        again = migrate(env)
        assert again.returncode == 0 and "current" in again.stdout
        assert drive(env)["login"] == 200

    assert table_count(db_file(home), "users") == before == 1
    assert list((home / "backups").glob("*.db")) == []


def test_old_database_is_backed_up_then_upgraded(tmp_path, dist):
    home = tmp_path / "home"
    env = env_for(home, dist)
    (home / "data").mkdir(parents=True)

    upgrade_old = run(["-c", UPGRADE_OLD], env)
    assert upgrade_old.returncode == 0, upgrade_old.stderr

    connection = sqlite3.connect(db_file(home))
    connection.execute("INSERT INTO institutes (name, created_at) VALUES ('Existing Institute', '2026-01-01')")
    connection.commit()
    connection.close()

    result = migrate(env)
    assert result.returncode == 0, result.stderr
    assert "upgraded" in result.stdout

    backups = list((home / "backups").glob("*pre-migration*.db"))
    assert len(backups) == 1
    assert table_count(backups[0], "institutes") == 1
    assert table_count(db_file(home), "institutes") == 1
    head = sqlite3.connect(db_file(home)).execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert head != "0002"


# --------------------------------------------------- fail closed

def test_unknown_revision_is_refused_and_untouched(tmp_path, dist):
    home = tmp_path / "home"
    env = env_for(home, dist)
    assert migrate(env).returncode == 0
    connection = sqlite3.connect(db_file(home))
    connection.execute("UPDATE alembic_version SET version_num = 'from_the_future'")
    connection.commit()
    connection.close()
    before = sha(db_file(home))

    result = migrate(env)
    assert result.returncode != 0 and "does not know" in result.stderr
    assert sha(db_file(home)) == before


def test_tables_without_migration_history_are_refused(tmp_path, dist):
    home = tmp_path / "home"
    (home / "data").mkdir(parents=True)
    connection = sqlite3.connect(db_file(home))
    connection.execute("CREATE TABLE precious (id INTEGER)")
    connection.commit()
    connection.close()
    before = sha(db_file(home))

    result = migrate(env_for(home, dist))
    assert result.returncode != 0 and "no migration history" in result.stderr
    assert sha(db_file(home)) == before


def test_failed_safety_backup_stops_the_migration(tmp_path, dist):
    home = tmp_path / "home"
    env = env_for(home, dist)
    (home / "data").mkdir(parents=True)
    assert run(["-c", UPGRADE_OLD], env).returncode == 0
    before = sha(db_file(home))

    # Make the backup step fail, then try to start.
    script = (
        "from backend.app.ops import backup\n"
        "def boom(*a, **k): raise backup.BackupError('disk full')\n"
        "backup.create_backup = boom\n"
        "from backend.app.database.connection import engine\n"
        "from backend.app.database.startup import prepare_database, StartupError\n"
        "try:\n    prepare_database(engine)\n"
        "except StartupError as e:\n    print('REFUSED', e)\n"
    )
    result = run(["-c", script], env)
    assert "REFUSED" in result.stdout and "safety backup" in result.stdout
    assert sha(db_file(home)) == before


def test_unwritable_backup_location_is_a_clear_refusal(tmp_path, dist):
    (tmp_path / "not-a-dir").write_text("a file, not a directory")
    result = migrate(env_for(tmp_path / "home", dist,
                             COACHING_BACKUP_DIR=str(tmp_path / "not-a-dir")))
    assert result.returncode != 0 and "Refused" in result.stderr
    assert "Traceback" not in result.stderr


def test_development_mode_never_migrates_automatically(tmp_path):
    env = env_for(tmp_path, COACHING_APP_MODE="development",
                  COACHING_DB_PATH=str(tmp_path / "dev.db"))
    result = run(
        ["-c", "from fastapi.testclient import TestClient; "
               "from backend.app.main import app\n"
               "try:\n    TestClient(app).__enter__()\n"
               "except RuntimeError as e:\n    print('REFUSED', e)"],
        env,
    )
    assert "REFUSED" in result.stdout and "alembic upgrade head" in result.stdout
    assert table_count(tmp_path / "dev.db", "sqlite_master") == 0


def test_missing_frontend_build_stops_local_start(tmp_path):
    result = run(["-c", "import backend.app.main"],
                 env_for(tmp_path / "home", tmp_path / "no-dist"))
    assert result.returncode != 0 and "npm run build" in result.stderr


# --------------------------------------------------- the real launcher

def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def fetch(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def test_launcher_serves_the_app_on_loopback_and_survives_restart(tmp_path, dist):
    home = tmp_path / "home"
    port = free_port()
    env = env_for(home, dist, COACHING_PORT=str(port))

    for _ in range(2):
        server = subprocess.Popen(
            [sys.executable, "scripts/run_local.py"], cwd=PROJECT_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    status, body = fetch(f"http://127.0.0.1:{port}/api/health")
                    break
                except (urllib.error.URLError, ConnectionError, OSError):
                    assert server.poll() is None, server.stderr.read()
                    time.sleep(0.3)
            else:
                pytest.fail("server did not start")

            assert status == 200
            assert "FAKE-INDEX" in fetch(f"http://127.0.0.1:{port}/")[1]
        finally:
            server.terminate()
            server.wait(timeout=15)

    assert db_file(home).exists()


def test_launcher_warns_when_bound_beyond_loopback(tmp_path, dist):
    result = run(
        ["-c",
         "import os, sys; sys.argv=['run_local.py','--migrate-only']; "
         "import runpy; runpy.run_path('scripts/run_local.py', run_name='__main__')"],
        env_for(tmp_path / "home", dist, COACHING_HOST="0.0.0.0"),
    )
    assert result.returncode == 0, result.stderr
    assert "non-loopback" in result.stderr
