"""
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Create a standalone platform operator account.

Distinct from grant_platform_admin.py, which promotes an existing *tenant*
user. This creates an account that belongs to no tenant at all:
organization_id and role_id are both NULL.

That separation is the point. A promoted tenant admin wears two hats — they are
simultaneously a customer of the platform and an operator of it, so their
actions on their own workspace are indistinguishable from ordinary use, and
deleting their workspace would delete their operator account with it. A
standalone account has no workspace to confuse things with: it can only reach
/platform, because every tenant-scoped route resolves the caller's organization
and refuses a request that has none.

Run inside the backend container:

    docker exec -i chattermate-backend-1 python - \\
        --email ops@growmiq.io --name "Ops" --password 'S3cure!Pass' \\
      < scripts/create_platform_admin.py

Omit --password to have one generated and printed once.
"""

import argparse
import secrets
import string
import sys

from app.core.security import validate_password_strength
from app.database import SessionLocal
from app.models.user import User


def generate_password(length: int = 20) -> str:
    """A password nobody has to remember, so make it long rather than clever."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        try:
            # Generated at random, so it can miss a required character class by
            # chance; regenerate rather than hand back something the login
            # policy would later reject.
            validate_password_strength(candidate)
            return candidate
        except Exception:
            continue


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a standalone platform operator")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Platform Operator")
    parser.add_argument("--password", default=None,
                        help="Omit to generate one and print it once")
    args = parser.parse_args()

    email = args.email.strip().lower()

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            # Refuse rather than promote. Promoting silently would turn what
            # looks like a create into an escalation of somebody's existing
            # tenant account — exactly the confusion this script avoids.
            where = (
                f"tenant {existing.organization.domain}"
                if existing.organization_id and existing.organization
                else "the platform (standalone)"
            )
            print(
                f"{email} already exists, belonging to {where}.\n"
                "  To promote an existing tenant user instead, use "
                "grant_platform_admin.py --grant.",
                file=sys.stderr,
            )
            return 1

        password = args.password or generate_password()
        try:
            validate_password_strength(password)
        except Exception as e:
            print(f"Password rejected: {e}", file=sys.stderr)
            return 1

        user = User(
            email=email,
            full_name=args.name,
            hashed_password=User.get_password_hash(password),
            # No tenant, no role. Both are nullable, and every tenant-scoped
            # dependency refuses a caller without an organization — so this
            # account is structurally incapable of acting inside a customer's
            # workspace, rather than merely discouraged from it.
            organization_id=None,
            role_id=None,
            is_active=True,
            # No mailbox to verify against, and no signup flow ran.
            is_email_verified=True,
            is_platform_admin=True,
        )
        db.add(user)
        db.commit()

        print(f"Created platform operator {email}")
        print(f"  Sign in at /login, then open /platform")
        if not args.password:
            print()
            print(f"  Password: {password}")
            print("  Shown once and not stored anywhere — save it now.")
        print()
        print("  This account belongs to no tenant. It can read and modify every")
        print("  customer on the platform, and every action is written to the")
        print("  platform audit log.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
