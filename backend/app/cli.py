"""Operator commands.

python -m app.cli migrate
python -m app.cli create-platform-admin --email ops@example.com --name "Ops Admin"
python -m app.cli seed-demo
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

from alembic.config import Config
from sqlalchemy import select

from alembic import command
from app.config import get_settings
from app.db import system_session
from app.errors import AppError
from app.models import Organization, User
from app.security import hash_password, password_problems
from app.services import tenancy

BACKEND_DIR = Path(__file__).resolve().parent.parent


def migrate() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")
    print("Database is up to date.")


def create_platform_admin(email: str, name: str) -> None:
    password = os.environ.get("OPSCORE_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    problems = password_problems(password)
    if problems:
        sys.exit("Password " + "; ".join(problems) + ".")
    with system_session() as session:
        email = tenancy.normalize_email(email)
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            session.add(
                User(email=email, full_name=name, password_hash=hash_password(password), is_platform_admin=True)
            )
            print(f"Created platform admin {email}.")
        else:
            user.is_platform_admin = True
            print(f"{email} already existed; it is now a platform admin (password unchanged).")


def seed_demo() -> None:
    """Load the four invented demo clients (see app/demo_seed.py)."""
    if get_settings().is_production:
        sys.exit("Refusing to load demo data in production.")
    from app import demo_seed  # local: only the demo needs it

    with system_session() as session:
        if session.scalar(select(Organization).where(Organization.slug == demo_seed.CLIENTS[0].slug)):
            print("Demo data is already loaded.")
            return
        created = demo_seed.load(session)

    print("Demo data loaded. Every demo account uses the password:", demo_seed.DEMO_PASSWORD)
    for spec, _ in created:
        print(f"  {spec.owner_email:<24} {spec.name} ({spec.blurb})")
    print("  supervisor@andes.demo    Andes Energy, supervisor role")
    print("Device API keys (shown once):")
    for spec, key in created:
        print(f"  {spec.name}: {key}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="OpsCore operator commands")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    admin = sub.add_parser("create-platform-admin", help="create the account that onboards clients")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    sub.add_parser("seed-demo", help="load four invented demo clients (not for production)")
    args = parser.parse_args()

    try:
        if args.command == "migrate":
            migrate()
        elif args.command == "create-platform-admin":
            create_platform_admin(args.email, args.name)
        elif args.command == "seed-demo":
            seed_demo()
    except AppError as exc:
        sys.exit(f"{exc.code}: {exc.message} {exc.details or ''}")


if __name__ == "__main__":
    main()
