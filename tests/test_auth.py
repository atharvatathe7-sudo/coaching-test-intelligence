"""
Authentication, sessions, CSRF and role checks (Milestone 4B).
"""

import hashlib
import itertools
import logging
import re
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.app import config
from backend.app.database import models
from backend.app.main import app
from backend.app.security.clock import utcnow
from backend.app.security.dependencies import current_user

from conftest import make_client

PUBLIC_ROUTES = {
    ("GET", "/"),
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
}

PASSWORD = "correct horse battery"
_counter = itertools.count(1)


def new_user(client, role="teacher", password=PASSWORD):
    email = f"user{next(_counter)}@auth.test"
    response = client.post(
        "/api/users",
        json={"name": "Test User", "email": email, "password": password, "role": role},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"], email


def login(test_client, email, password=PASSWORD):
    return test_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )


def _dependency_calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _dependency_calls(dep)


def _walk(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        # FastAPI wraps each include_router() in an object exposing the
        # original router; recurse so no included route is missed.
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _walk(inner.routes)


def _api_routes():
    for route in _walk(app.routes):
        for method in route.methods:
            yield method, route


def test_route_walker_sees_all_routes():
    """Guard against the guard: the walker must find the real route table."""
    paths = {route.path for _, route in _api_routes()}
    assert len(paths) >= 25
    assert {"/api/health", "/api/auth/login", "/api/imports/answers"} <= paths


# ------------------------------------------------------------------
# Route guard
# ------------------------------------------------------------------

def test_every_non_public_route_requires_authentication():
    """Structural check: current_user is in every protected route's tree."""
    protected = [
        (method, route)
        for method, route in _api_routes()
        if (method, route.path) not in PUBLIC_ROUTES
    ]
    unprotected = [
        (method, route.path)
        for method, route in protected
        if current_user not in set(_dependency_calls(route.dependant))
    ]
    assert len(protected) >= 25
    assert unprotected == []

    # Public routes really are reachable without the dependency.
    public = {(m, r.path) for m, r in _api_routes()} & PUBLIC_ROUTES
    assert public == PUBLIC_ROUTES


def test_every_non_public_route_returns_401_when_signed_out(anon_client):
    """Behavioural check: each protected route rejects an anonymous call."""
    checked = 0

    for method, route in _api_routes():
        if (method, route.path) in PUBLIC_ROUTES:
            continue

        path = re.sub(r"\{[^}]+\}", "1", route.path)
        response = anon_client.request(method, path, json={})

        assert response.status_code == 401, (method, path, response.text)
        checked += 1

    assert checked >= 25


def test_public_routes_work_signed_out(anon_client):
    assert anon_client.get("/").status_code == 200
    assert anon_client.get("/api/health").status_code == 200


def test_unsafe_legacy_routes_removed(client):
    for method, path in [
        ("POST", "/api/institutes"),
        ("GET", "/api/institutes"),
        ("GET", "/api/database/tables"),
        ("GET", "/api/status"),
    ]:
        assert client.request(method, path, json={}).status_code in (404, 405)


# ------------------------------------------------------------------
# Login
# ------------------------------------------------------------------

def test_valid_login_sets_secure_session_cookie(anon_client, db):
    response = login(anon_client, "teacher@demo.local", "demo-password")

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "teacher"
    assert response.json()["user"]["institute"]["id"] == 1

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{config.SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()

    # Only a hash of the token is stored.
    token = anon_client.cookies[config.SESSION_COOKIE_NAME]
    digest = hashlib.sha256(token.encode()).hexdigest()
    stored = db.query(models.UserSession).filter_by(token_hash=digest).one()
    assert stored.token_hash != token

    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "teacher@demo.local"


def test_email_is_case_insensitive(anon_client):
    assert login(anon_client, "  Teacher@Demo.LOCAL ", "demo-password").status_code == 200


def test_invalid_password_and_unknown_email_look_the_same(anon_client):
    wrong = login(anon_client, "teacher@demo.local", "not-the-password")
    unknown = login(anon_client, "nobody@nowhere.test", "not-the-password")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert config.SESSION_COOKIE_NAME not in anon_client.cookies


def test_passwords_are_hashed_with_argon2id(client, db):
    user_id, _ = new_user(client)
    user = db.get(models.User, user_id)

    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


def test_short_password_rejected(client):
    response = client.post(
        "/api/users",
        json={"name": "X", "email": "short@auth.test", "password": "123456789"},
    )
    assert response.status_code == 400
    assert "at least 10" in response.json()["detail"]


def test_failed_login_lockout(client, anon_client, db):
    user_id, email = new_user(client)

    for _ in range(config.LOGIN_MAX_FAILURES):
        assert login(anon_client, email, "wrong-password!").status_code == 401

    # Locked: even the correct password is refused.
    assert login(anon_client, email).status_code == 401

    user = db.get(models.User, user_id)
    db.refresh(user)
    assert user.locked_until > utcnow()

    # After the lock expires, the correct password works and resets state.
    user.locked_until = utcnow() - timedelta(seconds=1)
    db.commit()
    assert login(anon_client, email).status_code == 200

    db.refresh(user)
    assert user.failed_login_count == 0
    assert user.locked_until is None


def test_success_resets_failure_count(client, anon_client, db):
    user_id, email = new_user(client)
    for _ in range(3):
        login(anon_client, email, "wrong-password!")

    assert login(anon_client, email).status_code == 200
    user = db.get(models.User, user_id)
    db.refresh(user)
    assert user.failed_login_count == 0


def test_disabled_user_rejected_and_sessions_revoked(client):
    user_id, email = new_user(client)
    signed_in = make_client(email, PASSWORD)
    assert signed_in.get("/api/auth/me").status_code == 200

    response = client.patch(f"/api/users/{user_id}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    assert signed_in.get("/api/auth/me").status_code == 401
    assert login(TestClient(app, headers={"X-Requested-With": "fetch"}), email).status_code == 401

    client.patch(f"/api/users/{user_id}", json={"is_active": True})
    assert make_client(email, PASSWORD).get("/api/auth/me").status_code == 200


def test_login_does_not_log_password(anon_client, caplog):
    caplog.set_level(logging.DEBUG)
    login(anon_client, "teacher@demo.local", "a-secret-attempt-123")
    login(anon_client, "nobody@nowhere.test", "a-secret-attempt-123")
    assert "a-secret-attempt-123" not in caplog.text


# ------------------------------------------------------------------
# Sessions
# ------------------------------------------------------------------

def _session_of(test_client, db):
    token = test_client.cookies[config.SESSION_COOKIE_NAME]
    digest = hashlib.sha256(token.encode()).hexdigest()
    return db.query(models.UserSession).filter_by(token_hash=digest).one()


def test_logout_revokes_session(teacher_client, db):
    token = teacher_client.cookies[config.SESSION_COOKIE_NAME]

    assert teacher_client.post("/api/auth/logout").status_code == 200
    assert teacher_client.get("/api/auth/me").status_code == 401

    # Replaying the old cookie does not work either.
    replay = TestClient(app, cookies={config.SESSION_COOKIE_NAME: token})
    assert replay.get("/api/auth/me").status_code == 401


def test_idle_expiry(teacher_client, db):
    session = _session_of(teacher_client, db)
    session.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    assert teacher_client.get("/api/auth/me").status_code == 401


def test_absolute_expiry(teacher_client, db):
    session = _session_of(teacher_client, db)
    session.created_at = utcnow() - timedelta(days=config.SESSION_ABSOLUTE_DAYS, seconds=1)
    session.expires_at = utcnow() + timedelta(hours=1)
    db.commit()

    assert teacher_client.get("/api/auth/me").status_code == 401


def test_sliding_expiry_extends_active_session(teacher_client, db):
    session = _session_of(teacher_client, db)
    session.last_seen_at = utcnow() - timedelta(hours=1)
    session.expires_at = utcnow() + timedelta(minutes=5)
    db.commit()

    assert teacher_client.get("/api/auth/me").status_code == 200

    db.refresh(session)
    assert session.expires_at > utcnow() + timedelta(hours=config.SESSION_IDLE_HOURS - 1)


def test_tampered_or_missing_cookie_rejected(anon_client):
    anon_client.cookies.set(config.SESSION_COOKIE_NAME, "made-up-token")
    assert anon_client.get("/api/auth/me").status_code == 401


def test_password_change(client):
    _, email = new_user(client)
    first = make_client(email, PASSWORD)
    second = make_client(email, PASSWORD)

    wrong = first.post(
        "/api/auth/password",
        json={"current_password": "nope-nope-nope", "new_password": "a-new-password-1"},
    )
    assert wrong.status_code == 400

    short = first.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "short"},
    )
    assert short.status_code == 400

    ok = first.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "a-new-password-1"},
    )
    assert ok.status_code == 200
    assert ok.json()["other_sessions_revoked"] == 1

    assert first.get("/api/auth/me").status_code == 200    # this session kept
    assert second.get("/api/auth/me").status_code == 401   # others revoked

    anon = TestClient(app, headers={"X-Requested-With": "fetch"})
    assert login(anon, email, PASSWORD).status_code == 401
    assert login(anon, email, "a-new-password-1").status_code == 200


# ------------------------------------------------------------------
# CSRF
# ------------------------------------------------------------------

def test_write_without_csrf_header_rejected():
    plain = TestClient(app)

    assert plain.post(
        "/api/auth/login",
        json={"email": "teacher@demo.local", "password": "demo-password"},
    ).status_code == 403

    signed_in = make_client("teacher@demo.local")
    no_header = TestClient(app, cookies=dict(signed_in.cookies))

    response = no_header.post(
        "/api/actions", json={"test_id": 1, "action_type": "review"}
    )
    assert response.status_code == 403
    assert no_header.post("/api/auth/logout").status_code == 403

    # Reads need no header; the session is still valid.
    assert no_header.get("/api/auth/me").status_code == 200


def test_write_with_csrf_header_accepted(teacher_client):
    response = teacher_client.post(
        "/api/actions", json={"test_id": 1, "action_type": "review"}
    )
    assert response.status_code == 200


# ------------------------------------------------------------------
# Roles
# ------------------------------------------------------------------

def test_teacher_cannot_use_admin_routes(teacher_client):
    forbidden = [
        ("POST", "/api/batches", {"name": "Teacher batch"}),
        ("POST", "/api/tests/1/evaluate", None),
        ("GET", "/api/users", None),
        ("POST", "/api/users", {"name": "x", "email": "x@y.test", "password": "x" * 12}),
        ("PATCH", "/api/users/1", {"is_active": False}),
        ("POST", "/api/users/1/password", {"new_password": "x" * 12}),
    ]
    for method, path, body in forbidden:
        response = teacher_client.request(method, path, json=body)
        assert response.status_code == 403, (method, path)

    for path in ("roster", "test-setup", "answers"):
        response = teacher_client.post(
            f"/api/imports/{path}",
            data={"batch_id": "1", "test_id": "1"},
            files={"file": ("f.csv", b"a,b\n", "text/csv")},
        )
        assert response.status_code == 403, path


def test_teacher_can_use_teacher_routes(teacher_client):
    for path in (
        "/api/batches", "/api/tests", "/api/tests/1",
        "/api/tests/1/analytics/batch", "/api/tests/1/action-report",
        "/api/tests/1/questions/1/investigation", "/api/tests/1/actions",
        "/api/tests/1/actions/outcomes", "/api/tests/1/compare/2",
    ):
        assert teacher_client.get(path).status_code == 200, path


def test_admin_can_use_admin_routes(client):
    assert client.post("/api/tests/1/evaluate").status_code == 200
    assert client.get("/api/users").status_code == 200


# ------------------------------------------------------------------
# User management
# ------------------------------------------------------------------

def test_user_management(client):
    user_id, email = new_user(client)

    listed = client.get("/api/users").json()["users"]
    assert email in [u["email"] for u in listed]
    assert all("password" not in key for u in listed for key in u)

    duplicate = client.post(
        "/api/users",
        json={"name": "Dup", "email": email.upper(), "password": PASSWORD},
    )
    assert duplicate.status_code == 409

    signed_in = make_client(email, PASSWORD)
    reset = client.post(
        f"/api/users/{user_id}/password", json={"new_password": "reset-password-99"}
    )
    assert reset.status_code == 200
    assert reset.json()["sessions_revoked"] == 1
    assert signed_in.get("/api/auth/me").status_code == 401
    assert make_client(email, "reset-password-99").get("/api/auth/me").status_code == 200

    promoted = client.patch(f"/api/users/{user_id}", json={"role": "admin"})
    assert promoted.json()["role"] == "admin"


def test_admin_cannot_disable_or_demote_self(client):
    me = client.get("/api/auth/me").json()["user"]

    assert client.patch(f"/api/users/{me['id']}", json={"is_active": False}).status_code == 400
    assert client.patch(f"/api/users/{me['id']}", json={"role": "teacher"}).status_code == 400
    assert client.get("/api/auth/me").status_code == 200
