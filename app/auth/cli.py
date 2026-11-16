"""Command-line admin tasks that must not be exposed over HTTP.

Usage: uv run python -m app.auth.cli create-tenant --name acme --admin-email admin@acme.example.com
Non-interactive (CI, containers): add --password-env NAME to read the password from $NAME.
"""

import argparse
import getpass
import os
import sys

from pydantic import ValidationError

from app.auth import service
from app.auth.models import Role
from app.auth.schemas import CreateUserRequest
from app.core.db import get_sessionmaker
from app.core.errors import ConflictError


def _prompt_password() -> str | None:
    # Prompted rather than passed as an argument, so it never lands in shell history.
    password = getpass.getpass("Admin password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return None
    return password


def _password_from_env(name: str) -> str | None:
    # The variable's name is an argument, never its value, so the password stays out of argv.
    password = os.environ.get(name)
    if not password:
        print(f"Environment variable {name} is not set or empty.", file=sys.stderr)
        return None
    return password


def _create_tenant(name: str, admin_email: str, password_env: str | None) -> int:
    password = _prompt_password() if password_env is None else _password_from_env(password_env)
    if password is None:
        return 1
    try:
        # Reuse the API's validation rules for email and password strength.
        admin = CreateUserRequest(email=admin_email, password=password, role=Role.ADMIN)
    except ValidationError as exc:
        print(f"Invalid input:\n{exc}", file=sys.stderr)
        return 1

    with get_sessionmaker()() as session:
        try:
            tenant, user = service.create_tenant_with_admin(
                session, name, admin.email, admin.password
            )
        except ConflictError as exc:
            print(exc.message, file=sys.stderr)
            return 1
    print(f"Created tenant '{tenant.name}' ({tenant.id}) with admin {user.email}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.auth.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-tenant", help="Create a tenant and its first admin")
    create.add_argument("--name", required=True, help="Unique tenant name")
    create.add_argument("--admin-email", required=True, help="Email of the first admin")
    create.add_argument(
        "--password-env", metavar="NAME", help="Read the admin password from this env variable"
    )

    args = parser.parse_args(argv)
    return _create_tenant(args.name, args.admin_email, args.password_env)


if __name__ == "__main__":
    sys.exit(main())
