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

Fail the build if platform-operator access becomes reachable over HTTP.

users.is_platform_admin is the highest privilege in the system: it crosses the
tenant boundary that everything else exists to enforce. It is writable only by
scripts/grant_platform_admin.py, which needs shell access.

A grep is too blunt to police that. The field legitimately appears in
UserResponse — the SPA needs it to decide whether to draw the console link — so
"the word appears in schemas/" is not the violation. The violation is the field
appearing in a model FastAPI parses a request *body* into, because Pydantic
would then happily set it from JSON.

So this parses the schema modules and checks which classes declare the field,
allowing only response models.
"""

import ast
import pathlib
import sys

SCHEMAS = pathlib.Path("backend/app/models/schemas")
FIELD = "is_platform_admin"

# A response model is only ever serialised outward. Anything else may end up as
# a request body, so the field must not appear in it.
def is_response_model(class_name: str) -> bool:
    return class_name.endswith("Response") or class_name.endswith("Out")


def main() -> int:
    violations = []
    for path in SCHEMAS.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            print(f"could not parse {path}: {e}", file=sys.stderr)
            return 1

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                # `is_platform_admin: bool = ...` is an AnnAssign; a plain
                # `is_platform_admin = ...` is an Assign. Catch both.
                names = []
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    names = [stmt.target.id]
                elif isinstance(stmt, ast.Assign):
                    names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                if FIELD in names and not is_response_model(node.name):
                    violations.append((path, node.name, stmt.lineno))

    if violations:
        for path, cls, line in violations:
            print(
                f"::error file={path},line={line}::{cls} declares {FIELD}. "
                "Only response models may expose it — a request model would let "
                "any caller grant themselves platform access.",
                file=sys.stderr,
            )
        return 1

    print(f"OK: {FIELD} appears only in response models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
