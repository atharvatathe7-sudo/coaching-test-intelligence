"""
Operator commands (run on the server, from the project root).

  python scripts/manage.py create-institute --name "ABC Academy" \
      --admin-name "Priya Sharma" --admin-email priya@abc.example
  python scripts/manage.py create-user --institute-id 1 \
      --name "Ravi Kumar" --email ravi@abc.example --role teacher
  python scripts/manage.py reset-password --email ravi@abc.example
  python scripts/manage.py set-active --email ravi@abc.example --inactive
  python scripts/manage.py list-users --institute-id 1

Passwords are prompted for (not echoed), or read from standard input with
--password-stdin. They are never accepted as command-line arguments,
which would leave them in shell history and process listings.

Institutes and their first administrator can only be created here: the
web API has no institute creation and no self-signup.
"""

import argparse
import getpass
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.database.connection import SessionLocal, engine  # noqa: E402
from backend.app.database.models import Institute, User  # noqa: E402
from backend.app.database.schema_check import require_current_schema  # noqa: E402
from backend.app.security.passwords import (  # noqa: E402
    PasswordPolicyError,
    hash_password,
)
from backend.app.security.sessions import revoke_user_sessions  # noqa: E402


def read_password(args) -> str:
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\n")

    first = getpass.getpass("Password: ")
    second = getpass.getpass("Repeat password: ")

    if first != second:
        raise SystemExit("Passwords do not match.")

    return first


def make_user(db, institute_id, name, email, role, password) -> User:
    email = email.strip().lower()

    if db.query(User).filter(User.email == email).first():
        raise SystemExit(f"A user with email {email} already exists.")

    try:
        password_hash = hash_password(password)
    except PasswordPolicyError as exc:
        raise SystemExit(str(exc))

    user = User(
        institute_id=institute_id,
        name=name.strip(),
        email=email,
        password_hash=password_hash,
        role=role,
        is_active=True,
    )
    db.add(user)
    return user


def find_user(db, email) -> User:
    user = db.query(User).filter(User.email == email.strip().lower()).first()

    if user is None:
        raise SystemExit(f"No user with email {email}.")

    return user


def cmd_create_institute(db, args):
    name = args.name.strip()

    if not name:
        raise SystemExit("Institute name is required.")

    institute = Institute(name=name)
    db.add(institute)
    db.flush()
    make_user(
        db, institute.id, args.admin_name, args.admin_email, "admin",
        read_password(args),
    )
    db.commit()
    print(f"Created institute {institute.id} ({name}) and its admin.")


def cmd_create_user(db, args):
    if db.get(Institute, args.institute_id) is None:
        raise SystemExit(f"No institute {args.institute_id}.")

    user = make_user(
        db, args.institute_id, args.name, args.email, args.role,
        read_password(args),
    )
    db.commit()
    print(f"Created {user.role} {user.email} (id {user.id}).")


def cmd_reset_password(db, args):
    user = find_user(db, args.email)

    try:
        user.password_hash = hash_password(read_password(args))
    except PasswordPolicyError as exc:
        raise SystemExit(str(exc))

    user.failed_login_count = 0
    user.locked_until = None
    revoked = revoke_user_sessions(db, user.id)
    db.commit()
    print(f"Password reset for {user.email}; {revoked} session(s) revoked.")


def cmd_set_active(db, args):
    user = find_user(db, args.email)
    user.is_active = args.active

    if not args.active:
        revoked = revoke_user_sessions(db, user.id)
    else:
        user.failed_login_count = 0
        user.locked_until = None
        revoked = 0

    db.commit()
    state = "enabled" if args.active else "disabled"
    print(f"{user.email} {state}; {revoked} session(s) revoked.")


def cmd_list_users(db, args):
    query = db.query(User).order_by(User.institute_id, User.id)

    if args.institute_id is not None:
        query = query.filter(User.institute_id == args.institute_id)

    for user in query:
        state = "active" if user.is_active else "disabled"
        print(
            f"{user.id}\tinstitute {user.institute_id}\t{user.role}\t"
            f"{state}\t{user.email}"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-institute")
    p.add_argument("--name", required=True)
    p.add_argument("--admin-name", required=True)
    p.add_argument("--admin-email", required=True)
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(func=cmd_create_institute)

    p = sub.add_parser("create-user")
    p.add_argument("--institute-id", type=int, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--role", choices=["admin", "teacher"], default="teacher")
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("reset-password")
    p.add_argument("--email", required=True)
    p.add_argument("--password-stdin", action="store_true")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("set-active")
    p.add_argument("--email", required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--active", dest="active", action="store_true")
    group.add_argument("--inactive", dest="active", action="store_false")
    p.set_defaults(func=cmd_set_active)

    p = sub.add_parser("list-users")
    p.add_argument("--institute-id", type=int)
    p.set_defaults(func=cmd_list_users)

    args = parser.parse_args(argv)

    require_current_schema(engine)
    db = SessionLocal()

    try:
        args.func(db, args)
    finally:
        db.close()


if __name__ == "__main__":
    main()
