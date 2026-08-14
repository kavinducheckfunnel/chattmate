#!/usr/bin/env python3
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

Every feature in the catalog must be enforced somewhere, and every enforced
feature must be in the catalog.

The operator console renders FEATURE_CATALOG as a matrix of switches. A switch
with no code behind it is worse than a missing switch: it tells an operator
they have taken a capability away from a paying customer when they have not.
The opposite mistake is quieter but just as bad — a gate keyed to a string
absent from the catalog can never be turned on, so the feature is dead for
everyone and nothing in the console explains why.

An AST walk rather than grep: the gate calls span several lines, so the feature
key and the function name are rarely on the same line, and a line-oriented
search either misses them or matches the docstring that mentions them.

Exit 0 when the two sets agree; 1 otherwise, naming the offenders.
"""

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
CATALOG_FILE = BACKEND / "app" / "models" / "feature.py"

# Functions whose first string-literal feature argument counts as enforcement.
# Position differs between them, hence the index.
GATE_CALLS = {
    "check_feature_access": 2,   # (db, org_id, feature, message)
    "feature_allowed": 2,        # (db, org_id, feature)
    "is_enabled": 2,             # (db, org_id, feature)
}


def catalog_keys() -> set[str]:
    """Feature keys declared in FEATURE_CATALOG."""
    tree = ast.parse(CATALOG_FILE.read_text())
    for node in ast.walk(tree):
        # The catalog carries a type annotation, so it parses as AnnAssign
        # rather than Assign. Handling only one of the two silently found
        # nothing and reported the catalog as empty.
        if isinstance(node, ast.AnnAssign):
            names = [node.target.id] if isinstance(node.target, ast.Name) else []
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        else:
            continue
        if "FEATURE_CATALOG" not in names or node.value is None:
            continue
        keys = set()
        for element in getattr(node.value, "elts", []):
            # FeatureDef("key", ...) — the key is the first positional argument.
            if (isinstance(element, ast.Call) and element.args
                    and isinstance(element.args[0], ast.Constant)):
                keys.add(element.args[0].value)
        return keys
    return set()


def enforced_keys() -> dict[str, list[str]]:
    """Feature keys passed to a gate call, mapped to where they were found."""
    found: dict[str, list[str]] = {}
    for path in sorted(BACKEND.glob("app/**/*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as e:
            print(f"::error file={path}::cannot parse: {e}")
            continue
        # Module-level string constants, so `check_feature_access(db, org,
        # AI_TICKETING_FEATURE, ...)` resolves. Naming the key once and reusing
        # it is better style than repeating the literal, and the checker should
        # not push callers towards the worse pattern to stay visible.
        constants: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = node.value.value

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            index = GATE_CALLS.get(name)
            if index is None or len(node.args) <= index:
                continue
            arg = node.args[index]
            key = None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                key = arg.value
            elif isinstance(arg, ast.Name):
                # Unresolvable names are skipped rather than guessed — a gate
                # whose key is computed at runtime cannot be checked here, and
                # inventing a key would produce a false pass.
                key = constants.get(arg.id)
            if key:
                rel = path.relative_to(REPO)
                found.setdefault(key, []).append(f"{rel}:{node.lineno}")
    return found


def main() -> int:
    declared = catalog_keys()
    if not declared:
        print("::error::FEATURE_CATALOG is empty or could not be parsed")
        return 1

    enforced = enforced_keys()
    failed = False

    decorative = sorted(declared - set(enforced))
    if decorative:
        failed = True
        for key in decorative:
            print(
                f"::error file=backend/app/models/feature.py::feature {key!r} is in the "
                "catalog but no code gates on it — the console would show a switch "
                "that changes nothing"
            )

    # feature_allowed is also used by the enterprise module's own keys, which
    # legitimately live outside this catalog. Only flag keys gated inside this
    # repository's own service layer.
    orphans = sorted(k for k in enforced if k not in declared)
    if orphans:
        failed = True
        for key in orphans:
            sites = ", ".join(enforced[key])
            print(
                f"::error::feature {key!r} is gated at {sites} but is not in "
                "FEATURE_CATALOG — no operator can ever turn it on"
            )

    if not failed:
        print(f"OK: {len(declared)} features, all enforced and all reachable")
        for key in sorted(declared):
            print(f"  {key:18s} {enforced[key][0]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
