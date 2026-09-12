import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from tools.verify_public_release import MANIFEST, PACKAGE_ROOT, verify_archive


class PublicArchiveTests(unittest.TestCase):
    def build(self, directory, extra=None, content=b"source", expected=b"source"):
        archive_path = Path(directory) / "preview.tar.gz"
        manifest = (hashlib.sha256(expected).hexdigest() + "  README.md\n").encode()
        with tarfile.open(archive_path, "w:gz") as archive:
            for name, data in (("README.md", content), (MANIFEST, manifest)):
                member = tarfile.TarInfo(PACKAGE_ROOT + "/" + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            if extra:
                archive.addfile(extra)
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        archive_path.with_name(archive_path.name + ".sha256").write_text(
            digest + "  " + archive_path.name + "\n"
        )
        return archive_path

    def test_valid_archive_extracts_verified_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = verify_archive(self.build(directory), Path(directory))
            self.assertEqual((root / "README.md").read_bytes(), b"source")

    def test_modified_file_is_rejected_even_with_matching_archive_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.build(directory, content=b"modified")
            with self.assertRaisesRegex(ValueError, "manifest mismatch"):
                verify_archive(archive, Path(directory))
            self.assertFalse((Path(directory) / PACKAGE_ROOT).exists())

    def test_traversal_link_duplicate_and_unmanifested_file_are_rejected(self):
        cases = []
        for name in (PACKAGE_ROOT + "/../escape", PACKAGE_ROOT + "/README.md", PACKAGE_ROOT + "/extra"):
            cases.append(tarfile.TarInfo(name))
        link = tarfile.TarInfo(PACKAGE_ROOT + "/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "README.md"
        cases.append(link)
        for member in cases:
            with self.subTest(member=member.name), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    verify_archive(self.build(directory, extra=member), Path(directory))
                self.assertFalse((Path(directory) / PACKAGE_ROOT).exists())

    def test_wrong_sidecar_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.build(directory)
            archive.with_name(archive.name + ".sha256").write_text("0" * 64 + "  preview.tar.gz\n")
            with self.assertRaisesRegex(ValueError, "sidecar"):
                verify_archive(archive, Path(directory))
