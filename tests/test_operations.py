"""
Operations (Milestone 4E): backups, restore verification, retention,
pre-operation safety backups, upload limits, production settings and
log hygiene.
"""

import asyncio
import json
import logging
import os
import sqlite3
import stat
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.app import config
from backend.app.database import models
from backend.app.database.connection import DATABASE_PATH
from backend.app.database.schema_check import expected_revision
from backend.app.ops import backup
from backend.app.security.body_limit import BodySizeLimitMiddleware
from backend.app.services import importer

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def live_counts():
    connection = sqlite3.connect(DATABASE_PATH)
    try:
        return backup._counts(connection)
    finally:
        connection.close()


# ------------------------------------------------------------------
# Backup and verification
# ------------------------------------------------------------------

def test_online_backup_while_app_is_running(tmp_path, client):
    # The app has open connections and WAL is active.
    assert client.get("/api/health").status_code == 200

    path = backup.create_backup(DATABASE_PATH, tmp_path, "nightly")

    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700

    manifest = json.loads(backup.manifest_path(path).read_text())
    assert manifest["schema_revision"] == expected_revision()
    assert manifest["row_counts"] == live_counts()
    assert manifest["row_counts"]["student_answers"] > 0
    assert manifest["kind"] == "nightly"


def test_verify_restores_and_checks(tmp_path):
    path = backup.create_backup(DATABASE_PATH, tmp_path, "manual")

    result = backup.verify_backup(path)

    assert result.ok, result.problems
    assert result.checks["integrity_check"] == ["ok"]
    assert result.checks["foreign_key_violations"] == 0
    assert result.checks["schema_revision"] == expected_revision()
    assert result.checks["health"] == "ok"
    assert result.checks["checksum_matches_manifest"] is True


def test_verify_detects_tampering(tmp_path):
    path = backup.create_backup(DATABASE_PATH, tmp_path, "manual")

    connection = sqlite3.connect(path)
    deleted = connection.execute(
        "DELETE FROM student_answers WHERE id IN "
        "(SELECT id FROM student_answers LIMIT 5)"
    ).rowcount
    connection.commit()
    connection.close()
    assert deleted == 5

    result = backup.verify_backup(path)

    assert not result.ok
    assert any("Checksum" in p for p in result.problems)
    assert any("Row counts" in p for p in result.problems)


def test_verify_detects_corruption(tmp_path):
    path = backup.create_backup(DATABASE_PATH, tmp_path, "manual")
    data = bytearray(path.read_bytes())
    for offset in range(4096, len(data), 997):
        data[offset] = (data[offset] + 1) % 256
    path.write_bytes(bytes(data))

    try:
        result = backup.verify_backup(path)
        assert not result.ok
    except sqlite3.DatabaseError:
        pass  # unreadable is also a failed verification


def test_verify_rejects_wrong_revision(tmp_path):
    path = backup.create_backup(DATABASE_PATH, tmp_path, "manual")
    copy = tmp_path / "copy.db"
    backup._online_copy(path, copy)
    connection = sqlite3.connect(copy)
    connection.execute("UPDATE alembic_version SET version_num = '0001'")
    connection.commit()
    connection.close()

    result = backup.check_database_file(copy)
    assert not result.ok
    assert result.checks["health"] == "outdated"


def test_restore_replaces_target_and_keeps_previous(tmp_path):
    source = backup.create_backup(DATABASE_PATH, tmp_path / "backups", "manual")

    target = tmp_path / "live" / "coaching.db"
    target.parent.mkdir()
    old = sqlite3.connect(target)
    old.execute("CREATE TABLE old_data (x)")
    old.commit()
    old.close()
    Path(f"{target}-wal").write_bytes(b"stale wal")

    moved = backup.restore_backup(source, target)

    assert moved is not None and moved.exists()
    assert not Path(f"{target}-wal").exists()      # stale WAL moved aside
    assert Path(f"{moved}-wal").exists()

    restored = backup.check_database_file(target)
    assert restored.ok
    assert restored.checks["row_counts"] == json.loads(
        backup.manifest_path(source).read_text()
    )["row_counts"]


def test_restore_refuses_unverified_backup(tmp_path):
    source = backup.create_backup(DATABASE_PATH, tmp_path / "b", "manual")
    connection = sqlite3.connect(source)
    assert connection.execute("DELETE FROM sessions").rowcount >= 0
    assert connection.execute(
        "DELETE FROM student_answers WHERE id IN (SELECT id FROM student_answers LIMIT 1)"
    ).rowcount == 1
    connection.commit()
    connection.close()

    target = tmp_path / "target.db"
    target.write_bytes(b"")

    with pytest.raises(backup.BackupError, match="unverified"):
        backup.restore_backup(source, target)

    assert target.exists()  # untouched


def test_backup_cli_create_and_test_restore(tmp_path):
    env = {
        **os.environ,
        "COACHING_DB_PATH": str(DATABASE_PATH),
        "COACHING_BACKUP_DIR": str(tmp_path),
    }

    created = subprocess.run(
        [sys.executable, "scripts/backup.py", "create", "--kind", "nightly"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
    )
    assert created.returncode == 0, created.stderr

    tested = subprocess.run(
        [sys.executable, "scripts/backup.py", "test-restore"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
    )
    assert tested.returncode == 0, tested.stdout + tested.stderr
    assert json.loads(tested.stdout)["ok"] is True

    empty = subprocess.run(
        [sys.executable, "scripts/backup.py", "--backup-dir", str(tmp_path / "none"),
         "test-restore"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
    )
    assert empty.returncode == 1


# ------------------------------------------------------------------
# Retention
# ------------------------------------------------------------------

def test_retention_policy():
    now = datetime(2026, 10, 2, 3, 0)
    nightly = [
        (now - timedelta(days=d), "nightly", Path(f"n{d}.db")) for d in range(120)
    ]
    pre = [
        (now - timedelta(days=d, hours=5), "pre-delete-test", Path(f"p{d}.db"))
        for d in (1, 10, 20, 40)
    ]
    backups = sorted(nightly + pre, key=lambda b: b[0], reverse=True)

    removed = set(backup.select_for_pruning(backups, now=now))
    kept = {path for _, _, path in backups} - removed

    kept_nightly = sorted(int(p.stem[1:]) for p in kept if p.stem.startswith("n"))
    # 14 most recent days...
    assert kept_nightly[:14] == list(range(14))
    # ...plus one per week for 8 weeks: never more than 14 + 8 nightly.
    assert len(kept_nightly) <= 22
    assert max(kept_nightly) < 8 * 7 + 7
    # Pre-operation backups kept for 14 days only.
    assert {Path("p1.db"), Path("p10.db")} <= kept
    assert {Path("p20.db"), Path("p40.db")} <= removed
    # The newest backup is always kept.
    assert backups[0][2] in kept


def test_prune_removes_files_and_manifests(tmp_path):
    old = datetime.utcnow() - timedelta(days=60)
    for i in range(3):
        stamp = (old - timedelta(days=i)).strftime(backup.TIMESTAMP_FORMAT)
        (tmp_path / f"coaching-{stamp}-pre-x.db").write_bytes(b"x")
        (tmp_path / f"coaching-{stamp}-pre-x.json").write_text("{}")

    removed = backup.prune_backups(tmp_path)

    assert len(removed) == 2          # newest kept even though it is old
    assert len(list(tmp_path.glob("*.db"))) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


# ------------------------------------------------------------------
# Safety backups before destructive operations
# ------------------------------------------------------------------

def _scratch_test(client, name):
    batch_id = client.post("/api/batches", json={"name": f"Ops {name}"}).json()["id"]
    def up(path, text, data):
        return client.post(
            f"/api/imports/{path}", data={k: str(v) for k, v in data.items()},
            files={"file": ("f.csv", text.encode(), "text/csv")},
        ).json()
    up("roster", "roll_number,name\nO1,Ops One\n", {"batch_id": batch_id, "dry_run": False})
    test_id = up("test-setup", "question_number,correct_answer,chapter,topic\n1,A,Mechanics,Kinematics\n",
                 {"batch_id": batch_id, "test_name": name, "subject": "Physics",
                  "test_date": "2026-09-01", "dry_run": False})["summary"]["test_id"]
    up("answers", "roll_number,question_number,answer\nO1,1,A\n", {"test_id": test_id, "dry_run": False})
    return test_id, up


def test_destructive_operations_back_up_first(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path))
    test_id, up = _scratch_test(client, "Backup First")

    report = up("answers", "roll_number,question_number,answer\nO1,1,B\n",
                {"test_id": test_id, "replace": True, "dry_run": False})
    assert report["status"] == "imported"

    report = up("answer-key", "question_number,correct_answer,chapter,topic\n1,B,Mechanics,Kinematics\n",
                {"test_id": test_id, "dry_run": False})
    assert report["status"] == "imported"

    assert client.delete(f"/api/tests/{test_id}").status_code == 200

    kinds = [kind for _, kind, _ in backup.list_backups(tmp_path)]
    assert sorted(kinds) == ["pre-answer-key", "pre-delete-test", "pre-replace-answers"]
    for _, _, path in backup.list_backups(tmp_path):
        assert backup.verify_backup(path).ok, path.name


def test_failed_safety_backup_blocks_the_change(client, tmp_path, monkeypatch, db):
    test_id, up = _scratch_test(client, "Backup Fails")
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x")
    monkeypatch.setattr(config, "BACKUP_DIR", str(not_a_dir))

    response = client.delete(f"/api/tests/{test_id}")
    assert response.status_code == 503
    assert "Nothing was deleted" in response.json()["detail"]

    report = up("answers", "roll_number,question_number,answer\nO1,1,B\n",
                {"test_id": test_id, "replace": True, "dry_run": False})
    assert report["status"] == "invalid"
    assert "Nothing was changed" in report["errors"][0]["message"]

    db.expire_all()
    assert db.get(models.Test, test_id) is not None
    answer = db.query(models.StudentAnswer).filter_by(test_id=test_id).one()
    assert answer.answer == "A"


# ------------------------------------------------------------------
# Upload size limits
# ------------------------------------------------------------------

def test_oversized_upload_rejected_by_content_length(client):
    big = b"roll_number,name\n" + b"x" * (config.MAX_IMPORT_REQUEST_BYTES + 10)
    response = client.post(
        "/api/imports/roster", data={"batch_id": "1"},
        files={"file": ("big.csv", big, "text/csv")},
    )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]


def test_oversized_chunked_upload_rejected_while_streaming():
    """No Content-Length: the body is counted as it arrives."""
    calls = {"chunks_read": 0, "responded": None}

    async def app(scope, receive, send):
        while True:
            message = await receive()
            calls["chunks_read"] += 1
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    chunk = b"x" * (1024 * 1024)
    total_chunks = 30
    sent = {"n": 0}

    async def receive():
        sent["n"] += 1
        return {"type": "http.request", "body": chunk, "more_body": sent["n"] < total_chunks}

    async def send(message):
        if message["type"] == "http.response.start":
            calls["responded"] = message["status"]

    scope = {"type": "http", "method": "POST", "path": "/api/imports/roster", "headers": []}
    asyncio.run(BodySizeLimitMiddleware(app)(scope, receive, send))

    assert calls["responded"] == 413
    # Stopped as soon as the limit was crossed, not after the whole body.
    assert sent["n"] <= config.MAX_IMPORT_REQUEST_BYTES // len(chunk) + 1 < total_chunks


def test_declared_oversize_never_reaches_the_app():
    reached = []

    async def app(scope, receive, send):
        reached.append(True)

    async def receive():
        raise AssertionError("body must not be read")

    statuses = []

    async def send(message):
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    scope = {
        "type": "http", "method": "POST", "path": "/api/actions",
        "headers": [(b"content-length", str(config.MAX_REQUEST_BYTES + 1).encode())],
    }
    asyncio.run(BodySizeLimitMiddleware(app)(scope, receive, send))

    assert statuses == [413] and reached == []


def test_normal_json_requests_still_work(client):
    assert client.post("/api/actions", json={"test_id": 1, "action_type": "review"}).status_code == 200


# ------------------------------------------------------------------
# Production settings
# ------------------------------------------------------------------

PROD_SCRIPT = r"""
import sys
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app import config

assert config.IS_PRODUCTION and config.COOKIE_SECURE
mode = sys.argv[1]

if mode == "startup":
    try:
        with TestClient(app):
            pass
    except RuntimeError as exc:
        print("REFUSED:", exc)
    else:
        print("STARTED")
else:
    with TestClient(app, base_url="https://testserver", headers={"X-Requested-With": "fetch"}) as c:
        print("docs", c.get("/docs").status_code)
        print("openapi", c.get("/openapi.json").status_code)
        r = c.post("/api/auth/login", json={"email": "teacher@demo.local", "password": "demo-password"})
        print("login", r.status_code)
        print("cookie", r.headers.get("set-cookie"))
"""


def _run_production(mode, backup_dir):
    env = {**os.environ, "COACHING_ENV": "production", "COACHING_DB_PATH": str(DATABASE_PATH)}
    env.pop("COACHING_BACKUP_DIR", None)
    if backup_dir is not None:
        env["COACHING_BACKUP_DIR"] = str(backup_dir)
    result = subprocess.run(
        [sys.executable, "-c", PROD_SCRIPT, mode],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_production_requires_backup_directory(tmp_path):
    assert "REFUSED: COACHING_BACKUP_DIR must be set" in _run_production("startup", None)
    assert "REFUSED" in _run_production("startup", tmp_path / "missing")
    assert "STARTED" in _run_production("startup", tmp_path)


def test_production_hides_docs_and_secures_cookie(tmp_path):
    out = _run_production("requests", tmp_path)

    assert "docs 404" in out
    assert "openapi 404" in out
    assert "login 200" in out
    cookie = next(line for line in out.splitlines() if line.startswith("cookie"))
    assert "Secure" in cookie and "HttpOnly" in cookie


def test_seed_refuses_production():
    env = {**os.environ, "COACHING_ENV": "production", "COACHING_DB_PATH": str(DATABASE_PATH)}
    result = subprocess.run(
        [sys.executable, "scripts/seed_demo.py"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "Refusing to seed" in result.stderr


# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

def test_database_errors_do_not_log_student_data(client, caplog, monkeypatch):
    test_id, up = _scratch_test(client, "Log Hygiene")

    def leaky(db, *args, **kwargs):
        db.add(models.Student(batch_id=999999, roll_number="LEAK-ROLL-77",
                              name="Leaky Student Name"))
        db.flush()

    monkeypatch.setattr(importer, "evaluate_test", leaky)
    caplog.set_level(logging.DEBUG)

    report = up("answers", "roll_number,question_number,answer\nO1,1,C\n",
                {"test_id": test_id, "replace": True, "dry_run": False})

    assert report["status"] == "invalid"
    assert "Import commit failed" in caplog.text           # still diagnosable
    assert "IntegrityError" in caplog.text
    assert "parameters hidden" in caplog.text
    assert "Leaky Student Name" not in caplog.text
    assert "LEAK-ROLL-77" not in caplog.text
    assert "Leaky Student Name" not in json.dumps(report)
