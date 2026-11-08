"""Fail when the repository tracks files that must stay private (partner PDFs with promo codes, env files).

Usage, from the repository root:  python -m scripts.check_repo_hygiene
"""

import subprocess
import sys
from pathlib import PurePosixPath

ALLOWED_INFOS = {"Infos/README.md"}
BINARY_SUFFIXES = {".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".zip"}


def violations(paths):
    found = []
    for raw in paths:
        path = PurePosixPath(raw)
        if raw.startswith("Infos/") and raw not in ALLOWED_INFOS:
            found.append(f"{raw}: only Infos/README.md may be tracked under Infos/")
        elif path.suffix.lower() in BINARY_SUFFIXES:
            found.append(f"{raw}: document/archive files must not be committed")
        elif path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
            found.append(f"{raw}: environment files must not be committed")
    return found


def main() -> int:
    tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()
    problems = violations(tracked)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
