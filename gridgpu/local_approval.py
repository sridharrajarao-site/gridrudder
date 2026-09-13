"""Local HMAC approvals, with persistent fail-closed nonce claims.

This trusts the local account holding the key, not a remote signer. An account
able to replace the key or erase this directory can bypass replay protection.
Keep this directory across restarts; never recreate it to retry an approval.
Issuing an approval is not a substitute for fresh attended confirmation.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat

from .performance_trial import OperatorAuthorization
from .supervised_recovery import intent_digest


class LocalApprovalError(RuntimeError):
    pass


@dataclass(frozen=True)
class SignedLocalApproval:
    payload: str
    signature: str


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise LocalApprovalError("timezone-aware clock and expiry required")
    return result


class LocalApprovalAuthority:
    """Existing owner-only directory; all file operations use held directory FDs."""

    def __init__(self, directory, *, clock=lambda: datetime.now(timezone.utc)):
        self.directory = Path(directory).absolute()
        self.clock = clock

    def _directory(self):
        # Walk every component without following symlinks (including parents).
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in self.directory.parts[1:]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=fd)
                os.close(fd)
                fd = next_fd
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise LocalApprovalError("approval directory must be owned by caller with mode 0700")
            return fd
        except BaseException:
            os.close(fd)
            raise

    def initialize(self):
        """Explicitly provision a random key in an existing protected directory.

        Exclusive creation refuses overwriting any existing key. No hardware I/O.
        """
        directory = self._directory()
        try:
            fd = os.open("key", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            try:
                key = os.urandom(32)
                if os.write(fd, key) != len(key):
                    raise LocalApprovalError("incomplete key write")
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(directory)
        finally:
            os.close(directory)

    def _key(self, directory):
        fd = os.open("key", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                    stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size != 32):
                raise LocalApprovalError("key must be a private, singly linked 32-byte regular file")
            value = os.read(fd, 33)
            if len(value) != 32:
                raise LocalApprovalError("invalid key length")
            return value
        finally:
            os.close(fd)

    def _validate(self, approval, intent):
        current = self.clock()
        if current.utcoffset() is None:
            raise LocalApprovalError("timezone-aware clock required")
        if _time(approval.expires_at_utc) <= current:
            raise LocalApprovalError("approval expired")
        if _time(intent.created_at_utc) > current:
            raise LocalApprovalError("intent is in the future")
        if any(not isinstance(v, str) or not v.strip() for v in (approval.operator, approval.nonce)):
            raise LocalApprovalError("operator and nonce required")

    def _trial(self, config, approval, intent):
        expected = OperatorAuthorization.bind(config, approval_id=approval.approval_id,
            operator=approval.operator, expires_at_utc=approval.expires_at_utc, nonce=approval.nonce)
        if (approval != expected or intent.authorization_sha256 != approval.binding_sha256 or
                intent.host_id != config.host_id or intent.gpu_uuid != config.gpu_uuid or
                intent.target_watts != config.target_power_limit_watts):
            raise LocalApprovalError("approval does not bind the exact trial and intent")
        self._validate(approval, intent)
        return _encode(dict(version=1, purpose="trial", config=asdict(config),
                            approval=asdict(approval), intent=asdict(intent)))

    def _recovery(self, intent, approval):
        if approval.intent_sha256 != intent_digest(intent):
            raise LocalApprovalError("recovery approval does not bind intent")
        self._validate(approval, intent)
        return _encode(dict(version=1, purpose="recovery", approval=asdict(approval), intent=asdict(intent)))

    def _issue(self, payload):
        directory = self._directory()
        try:
            signature = hmac.new(self._key(directory), payload.encode(), hashlib.sha256).hexdigest()
            return SignedLocalApproval(payload, signature)
        finally:
            os.close(directory)

    def issue_trial(self, config, authorization, intent):
        return self._issue(self._trial(config, authorization, intent))

    def issue_recovery(self, intent, approval):
        return self._issue(self._recovery(intent, approval))

    def _verify(self, payload, signed, nonce, consume):
        if not isinstance(signed, SignedLocalApproval) or signed.payload != payload:
            return False
        directory = self._directory()
        try:
            expected = hmac.new(self._key(directory), payload.encode(), hashlib.sha256).hexdigest()
            if not isinstance(signed.signature, str) or not hmac.compare_digest(expected, signed.signature):
                return False
            if not consume:
                return True  # Authenticity only; never use alone as the actuation gate.
            filename = "used-" + hashlib.sha256(nonce.encode()).hexdigest()
            try:
                fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
            except FileExistsError:
                return False
            try:
                # A partial/empty claim is still consumed after a crash.
                record = (hashlib.sha256(payload.encode()).hexdigest() + "\n").encode()
                if os.write(fd, record) != len(record):
                    raise LocalApprovalError("incomplete nonce claim")
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(directory)
            return True
        finally:
            os.close(directory)

    def verify_trial(self, config, authorization, intent, signed, *, consume=True):
        try:
            return self._verify(self._trial(config, authorization, intent), signed,
                                authorization.nonce, consume)
        except (ValueError, TypeError, AttributeError, OSError, LocalApprovalError):
            return False

    def verify_recovery(self, intent, approval, signed, *, consume=True):
        try:
            return self._verify(self._recovery(intent, approval), signed, approval.nonce, consume)
        except (ValueError, TypeError, AttributeError, OSError, LocalApprovalError):
            return False
