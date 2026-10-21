"""Command-line admin tasks, run from the backend folder.

    .venv\\Scripts\\python -m app.manage add-admin person@company.com [more@company.com ...]

New people get the default password you type (it's never shown or stored in plain text) and must choose their
own password when they first sign in. People who already have an account are made admins; their password is
left alone unless you add --reset-password.
"""
import argparse
import getpass
import os
import sys
import uuid

from sqlalchemy import select

from . import audit, auth
from .db import SessionLocal
from .migrate import upgrade_database
from .models import UserRow

ACTOR = "Command line"


def _name_from_email(email: str) -> str:
    return " ".join(p.capitalize() for p in email.split("@")[0].replace("_", ".").replace("-", ".").split(".") if p) or email


def _ask_password(emails: list[str]) -> str:
    pw = os.environ.get("AQ_DEFAULT_PASSWORD")
    if pw:
        auth.check_password_rules(pw)
        return pw
    while True:
        pw = getpass.getpass(f"Default password (at least {auth.MIN_PASSWORD} characters, not shown): ")
        if getpass.getpass("Type it again: ") != pw:
            print("They don't match - try again.")
            continue
        try:
            for e in emails:
                auth.check_password_rules(pw, e)
        except Exception as exc:  # HTTPException from the shared rules
            print(getattr(exc, "detail", exc))
            continue
        return pw


def add_admins(emails: list[str], reset_password: bool) -> int:
    emails = [e.strip().lower() for e in emails]
    bad = [e for e in emails if "@" not in e or "." not in e.split("@")[-1]]
    if bad:
        print("Not an email address: " + ", ".join(bad))
        return 2
    upgrade_database()
    with SessionLocal() as db:
        existing = {u.email: u for u in db.scalars(select(UserRow).where(UserRow.email.in_(emails)))}
        need_pw = [e for e in emails if e not in existing or reset_password]
        password = _ask_password(need_pw) if need_pw else None
        for email in emails:
            u = existing.get(email)
            if u is None:
                u = UserRow(id=str(uuid.uuid4()), email=email, name=_name_from_email(email), password_hash=auth.hash_password(password),
                            role="admin", all_orgs=True, is_active=True, must_change_password=True)
                db.add(u)
                audit.record(db, ACTOR, "user.added", audit.who(u), "Role: admin (default password)")
                print(f"Added admin {email} - they'll choose their own password at first sign-in.")
                continue
            changes = []
            if u.role != "admin" or not u.is_active:
                changes.append("made admin")
            u.role, u.all_orgs, u.is_active = "admin", True, True
            if reset_password:
                u.password_hash, u.must_change_password, u.failed_logins, u.locked_until = auth.hash_password(password), True, 0, None
                auth.end_sessions(db, u.id)
                changes.append("password reset to the default")
            if changes:
                audit.record(db, ACTOR, "user.updated", audit.who(u), "; ".join(changes))
            print(f"{email}: " + (", ".join(changes) if changes else "already an admin, nothing changed."))
        db.commit()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description="Aquarient admin tasks")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add-admin", help="Create admins (or make existing people admins)")
    p.add_argument("emails", nargs="+")
    p.add_argument("--reset-password", action="store_true", help="Also set existing people's password to the default")
    args = parser.parse_args(argv)
    if args.cmd == "add-admin":
        return add_admins(args.emails, args.reset_password)
    return 1


if __name__ == "__main__":
    sys.exit(main())
