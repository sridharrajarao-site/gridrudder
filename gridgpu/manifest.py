"""Build and verify a self-contained release artifact manifest."""

from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
from typing import Any, Iterable, Mapping, Sequence, Tuple


class ManifestError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ManifestError("manifest value is not canonical JSON: {}".format(exc)) from exc


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ManifestError("unsupported manifest value: {}".format(type(value).__name__))


def discover_release_files(project_root: Path) -> Tuple[Path, ...]:
    """Select actual product source, tests, and binding specifications."""

    root = project_root.resolve(strict=True)
    selected = []
    for directory, pattern in (("gridgpu", "*.py"), ("tests", "test_*.py")):
        selected.extend((root / directory).glob(pattern))
    selected.extend((root / "docs" / name for name in ("gate-b-spec.md", "ADR-0001-mvp-architecture.md")))
    selected.append(root / "README.md")
    files = tuple(sorted(path for path in selected if path.is_file()))
    if not files:
        raise ManifestError("no release files discovered")
    return files


def build_artifact_manifest(
    project_root: Path,
    packet_root: Path,
    *,
    scenario_definitions: Sequence[Any],
    controller_parameters: Mapping[str, Any],
    gate_requirements: Sequence[Any],
    test_command: Sequence[str],
) -> Mapping[str, Any]:
    """Snapshot actual files into ``packet_root/files`` and describe them."""

    project = project_root.resolve(strict=True)
    packet = packet_root.resolve(strict=True)
    if not test_command or any(not isinstance(part, str) or not part for part in test_command):
        raise ManifestError("test command must contain non-empty strings")
    entries = []
    for source in discover_release_files(project):
        relative = source.relative_to(project)
        target = packet / "files" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ManifestError("refusing to overwrite artifact snapshot")
        shutil.copyfile(str(source), str(target))
        entries.append({
            "path": target.relative_to(packet).as_posix(),
            "project_path": relative.as_posix(),
            "size": target.stat().st_size,
            "sha256": file_sha256(target),
        })
    return {
        "manifest_version": 1,
        "files": entries,
        "runtime": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "executable": Path(sys.executable).name,
            "platform": platform.platform(),
        },
        "scenario_definitions": _serialize(scenario_definitions),
        "controller_parameters": _serialize(controller_parameters),
        "gate_requirements": _serialize(gate_requirements),
        "test_command": list(test_command),
    }


def write_new_manifest(packet_root: Path, manifest: Mapping[str, Any]) -> Path:
    path = packet_root / "manifest.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags, 0o600)
    except OSError as exc:
        raise ManifestError("cannot create manifest without overwrite: {}".format(exc)) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(dict(manifest)) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def verify_manifest_files(packet_root: Path, manifest: Mapping[str, Any]) -> Tuple[str, ...]:
    reasons = []
    packet = packet_root.resolve(strict=True)
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return ("manifest files are missing",)
    for entry in files:
        try:
            relative = Path(entry["path"])
            target = (packet / relative).resolve(strict=True)
            target.relative_to(packet)
            if target.stat().st_size != entry["size"]:
                reasons.append("artifact size mismatch: {}".format(relative))
            if file_sha256(target) != entry["sha256"]:
                reasons.append("artifact hash mismatch: {}".format(relative))
        except (KeyError, OSError, ValueError, TypeError):
            reasons.append("invalid or missing artifact entry")
    return tuple(reasons)
