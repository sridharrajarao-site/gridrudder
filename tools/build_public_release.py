#!/usr/bin/env python3
"""Build a fail-closed, sanitized GridRudder public source preview."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "gridrudder-public-preview.tar.gz"
PACKAGE_ROOT = "gridrudder-public-preview"

ROOT_FILES = {
    ".gitattributes",
    ".gitignore",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "NOTICE",
    "README.md",
    "SECURITY.md",
    "SUPPORT.md",
}
INCLUDED_DIRS = {".github", "docs", "gridgpu", "site", "tests", "tools"}
INCLUDED_ARTIFACTS = {"artifacts/demo.jsonl"}
EXCLUDED_DIR_NAMES = {
    ".git",
    ".next",
    ".openai",
    ".pytest_cache",
    ".ruff_cache",
    ".vinext",
    ".wrangler",
    "__pycache__",
    "dist",
    "node_modules",
}
EXCLUDED_SUFFIXES = {".key", ".p12", ".pem", ".pfx", ".pyc"}
ALLOWED_SUFFIXES = {
    "",
    ".css",
    ".gitignore",
    ".ico",
    ".json",
    ".jsonl",
    ".md",
    ".mjs",
    ".png",
    ".py",
    ".sql",
    ".svg",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}

SCANS = {
    "private-key marker": re.compile(rb"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY"),
    "private trial identifier": re.compile(rb"user-confirmed-\d{4}|GPU-[0-9a-f-]{16,}", re.I),
    "known private contact detail": re.compile(rb"(?:2344\s+Tanager|925[. -]?413[. -]?8038)", re.I),
    "common secret token": re.compile(rb"(?:sk-(?:live|test|proj)-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})"),
    "private IPv4 address": re.compile(
        rb"(?<![\d.])(?:10(?:\.\d{1,3}){3}|127(?:\.\d{1,3}){3}|169\.254(?:\.\d{1,3}){2}|"
        rb"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|192\.168(?:\.\d{1,3}){2})(?![\d.])"
    ),
}
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PUBLIC_EMAILS = {b"pilot@gridrudder.com", b"%@example.invalid"}


def candidates() -> list[Path]:
    selected = [ROOT / name for name in sorted(ROOT_FILES)]
    selected.extend(ROOT / name for name in sorted(INCLUDED_ARTIFACTS))
    for directory_name in sorted(INCLUDED_DIRS):
        directory = ROOT / directory_name
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(ROOT)
            if any(part in EXCLUDED_DIR_NAMES for part in relative.parts):
                continue
            if path.is_file():
                selected.append(path)
    return sorted(set(selected), key=lambda value: value.relative_to(ROOT).as_posix())


def validate_source(paths: list[Path]) -> None:
    errors: list[str] = []
    for path in paths:
        relative = path.relative_to(ROOT)
        if path.is_symlink():
            errors.append(f"symlink not allowed: {relative}")
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            errors.append(f"unsafe file type: {relative}")
        if path.suffix.lower() not in ALLOWED_SUFFIXES and path.name not in ROOT_FILES:
            errors.append(f"unreviewed file type: {relative}")
    if errors:
        raise SystemExit("public release refused:\n- " + "\n- ".join(errors))


def scan(paths: list[Path], base: Path) -> None:
    findings: list[str] = []
    for path in paths:
        relative = path.relative_to(base)
        data = path.read_bytes()
        if path.suffix.lower() == ".png":
            continue
        for label, pattern in SCANS.items():
            if pattern.search(data):
                findings.append(f"{label}: {relative}")
        unexpected_emails = {value.lower() for value in EMAIL.findall(data)} - PUBLIC_EMAILS
        if unexpected_emails:
            findings.append(f"unapproved email address: {relative}")
    if findings:
        raise SystemExit("sanitation scan refused public release:\n- " + "\n- ".join(findings))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    source_paths = candidates()
    validate_source(source_paths)
    scan(source_paths, ROOT)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gridrudder-public-") as temporary:
        stage = Path(temporary) / PACKAGE_ROOT
        for source in source_paths:
            relative = source.relative_to(ROOT)
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

        staged_paths = sorted((path for path in stage.rglob("*") if path.is_file()), key=lambda value: value.relative_to(stage).as_posix())
        scan(staged_paths, stage)
        manifest = stage / "PUBLIC_RELEASE_MANIFEST.sha256"
        manifest.write_text(
            "".join(f"{sha256(path)}  {path.relative_to(stage).as_posix()}\n" for path in staged_paths),
            encoding="utf-8",
        )

        temporary_archive = OUTPUT.with_suffix(".tmp")
        with tarfile.open(temporary_archive, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(stage.rglob("*"), key=lambda value: value.relative_to(stage).as_posix()):
                archive.add(path, arcname=(Path(PACKAGE_ROOT) / path.relative_to(stage)).as_posix(), recursive=False)
        os.replace(temporary_archive, OUTPUT)

    archive_digest = sha256(OUTPUT)
    OUTPUT.with_name(OUTPUT.name + ".sha256").write_text(
        f"{archive_digest}  {OUTPUT.name}\n", encoding="utf-8"
    )
    print(f"created {OUTPUT.relative_to(ROOT)}")
    print(f"sha256 {archive_digest}")


if __name__ == "__main__":
    main()
