#!/usr/bin/env python3
"""Require an author-matching DCO sign-off on every commit in a range."""

from __future__ import annotations

import re
import subprocess
import sys


SIGNOFF = re.compile(r"^Signed-off-by:\s*(.+?)\s*<([^<>]+)>\s*$", re.IGNORECASE | re.MULTILINE)


def git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8"
    )
    return result.stdout


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_dco.py BASE_SHA HEAD_SHA")
    base, head = sys.argv[1:]
    commits = [value for value in git("rev-list", "--reverse", f"{base}..{head}").splitlines() if value]
    if not commits:
        raise SystemExit("DCO check refused an empty pull-request commit range")

    failures: list[str] = []
    for commit in commits:
        author_name, author_email, body = git("show", "-s", "--format=%an%n%ae%n%B", commit).split("\n", 2)
        signoffs = {(name.strip().casefold(), email.strip().casefold()) for name, email in SIGNOFF.findall(body)}
        author = (author_name.strip().casefold(), author_email.strip().casefold())
        if author not in signoffs:
            failures.append(f"{commit[:12]} ({author_name} <{author_email}>)")

    if failures:
        raise SystemExit(
            "DCO check failed. Amend each listed commit with `git commit --amend --signoff` "
            "and rebase later commits if needed:\n- " + "\n- ".join(failures)
        )
    print(f"DCO check passed for {len(commits)} commit(s)")


if __name__ == "__main__":
    main()
