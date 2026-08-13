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

Grant or revoke platform-operator access.

This is the ONLY way users.is_platform_admin is ever written. There is no API
for it, deliberately: platform access crosses the tenant boundary that the rest
of the system exists to enforce, so obtaining it should require shell access to
the server rather than a request someone can be tricked into making. It is also
why the flag cannot be a Permission — the existing org-scoped "super_admin"
permission is self-grantable by any tenant admin.

Run inside the backend container:

    docker exec -i chattermate-backend-1 python - < scripts/grant_platform_admin.py --list
    docker exec -i chattermate-backend-1 python - < scripts/grant_platform_admin.py --grant you@example.com
    docker exec -i chattermate-backend-1 python - < scripts/grant_platform_admin.py --revoke them@example.com

Or, if the repo is mounted:

    docker exec chattermate-backend-1 python /app/scripts/grant_platform_admin.py --list
"""

import argparse
import sys

from app.database import SessionLocal
from app.models.user import User


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage platform operators")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--grant", metavar="EMAIL")
    group.add_argument("--revoke", metavar="EMAIL")
    group.add_argument("--list", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.list:
            operators = db.query(User).filter(User.is_platform_admin == True).all()
            if not operators:
                print("No platform operators.")
                return 0
            print(f"{len(operators)} platform operator(s):")
            for u in operators:
                print(f"  {u.email}  ({u.full_name or 'no name'})")
            return 0

        email = (args.grant or args.revoke).strip().lower()
        user = db.query(User).filter(User.email == email).first()
        if not user:
            # Listing near-misses would be an account-enumeration aid if this
            # ever ran anywhere less trusted than a root shell; the exact
            # address is required.
            print(f"No user with email {email!r}", file=sys.stderr)
            return 1

        if args.grant:
            if user.is_platform_admin:
                print(f"{email} is already a platform operator.")
                return 0
            user.is_platform_admin = True
            db.commit()
            print(f"GRANTED platform operator access to {email}")
            print("  This account can now read and modify every tenant on the platform.")
            return 0

        if not user.is_platform_admin:
            print(f"{email} is not a platform operator.")
            return 0

        remaining = db.query(User).filter(
            User.is_platform_admin == True, User.id != user.id
        ).count()
        if remaining == 0:
            # Locking everyone out is recoverable only by another shell session,
            # so make it a deliberate choice rather than a surprise.
            print(
                f"Refusing: {email} is the last platform operator. "
                "Grant access to someone else first, or nobody will be able to "
                "reach the console without another shell session.",
                file=sys.stderr,
            )
            return 1

        user.is_platform_admin = False
        db.commit()
        print(f"REVOKED platform operator access from {email}")
        print("  Takes effect immediately — the flag is re-read on every request.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
