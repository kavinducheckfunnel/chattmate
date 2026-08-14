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

It also checks the API layer for *assignment* to the field. Reading it there is
legitimate and common — the login response carries it so the SPA can decide
whether to draw the console link — so the earlier line-oriented guard, which
flagged any mention, fired on correct code. Writing it is the escalation path,
and an assignment is exactly what an AST can tell apart from a read.
"""

import ast
import pathlib
import sys

SCHEMAS = pathlib.Path("backend/app/models/schemas")
API = pathlib.Path("backend/app/api")
FIELD = "is_platform_admin"


# A response model is only ever serialised outward. Anything else may end up as
# a request body, so the field must not appear in it.
def is_response_model(class_name: str) -> bool:
    return class_name.endswith("Response") or class_name.endswith("Out")


def check_schemas() -> list[str]:
    problems = []
    for path in SCHEMAS.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            problems.append(f"::error file={path}::could not parse: {e}")
            continue

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
                    problems.append(
                        f"::error file={path},line={stmt.lineno}::{node.name} declares "
                        f"{FIELD}. Only response models may expose it — a request model "
                        "would let any caller grant themselves platform access."
                    )
    return problems


def check_no_api_writes() -> list[str]:
    """No handler may assign the flag. `user.is_platform_admin = True` in any
    request path is a one-line privilege escalation; `setattr` is the same thing
    spelled to evade a search, so it is caught too."""
    problems = []
    for path in API.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            problems.append(f"::error file={path}::could not parse: {e}")
            continue

        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == FIELD:
                    problems.append(
                        f"::error file={path},line={node.lineno}::assignment to {FIELD} "
                        "in an API module. The flag is set only by "
                        "scripts/grant_platform_admin.py, which needs shell access."
                    )

            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setattr" \
                    and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                    and node.args[1].value == FIELD:
                problems.append(
                    f"::error file={path},line={node.lineno}::setattr() targeting {FIELD} "
                    "in an API module."
                )
    return problems


def main() -> int:
    problems = check_schemas() + check_no_api_writes()
    if problems:
        for line in problems:
            print(line, file=sys.stderr)
        return 1

    print(f"OK: {FIELD} appears only in response models and is never assigned in app/api/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
