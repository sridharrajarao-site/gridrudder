#!/usr/bin/env python3
"""Verify a source preview and run its simulator from an isolated directory.

Checksums detect corruption, not authenticity. Only run this on a trusted build:
the smoke check executes the Python source inside the archive.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile


PACKAGE_ROOT = "gridrudder-public-preview"
MANIFEST = "PUBLIC_RELEASE_MANIFEST.sha256"


def verify_archive(archive_path: Path, destination: Path) -> Path:
    """Verify every regular member before extracting; reject links and traversal."""
    expected = archive_path.with_name(archive_path.name + ".sha256").read_text().split()
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if expected != [digest, archive_path.name]:
        raise ValueError("archive sidecar checksum mismatch")
    with tarfile.open(archive_path, "r:gz") as archive:
        files = {}
        seen = set()
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if (
                path.is_absolute() or ".." in path.parts
                or not path.parts or path.parts[0] != PACKAGE_ROOT
                or path.as_posix() != member.name
                or member.name in seen
                or not (member.isdir() or member.isfile())
            ):
                raise ValueError("unsafe or duplicate archive member")
            seen.add(member.name)
            if member.isfile():
                relative = path.relative_to(PACKAGE_ROOT).as_posix()
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("unreadable archive member")
                files[relative] = stream.read()
        manifest = files.pop(MANIFEST, None)
        if manifest is None:
            raise ValueError("missing per-file manifest")
        declared = {}
        for line in manifest.decode("utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if match is None or match[2] in declared:
                raise ValueError("invalid or duplicate manifest entry")
            declared[match[2]] = match[1]
        actual = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        if actual != declared:
            raise ValueError("per-file manifest mismatch")
        root = destination / PACKAGE_ROOT
        root.mkdir()
        for name, data in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (root / MANIFEST).write_bytes(manifest)
        return root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="gridrudder-smoke-") as directory:
        root = verify_archive(args.archive.resolve(), Path(directory))
        for command in (
            ["demo", "--output", "artifacts/smoke.jsonl"],
            ["gate-b-release", "--output", "artifacts/smoke-gate-b"],
            ["verify-audit", "artifacts/smoke-gate-b/release-audit.jsonl"],
            ["benchmark"],
        ):
            # Ignore Python environment overrides and user site packages. The
            # working directory contains only the verified source distribution.
            subprocess.run(
                [sys.executable, "-E", "-s", "-m", "gridgpu", *command],
                cwd=root, check=True, timeout=60,
            )
    print("Public source verified; isolated simulator, audit, and benchmark passed.")


if __name__ == "__main__":
    main()
