from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import threading
from typing import Any

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from openpilot.common.hardware.hw import Paths


PUBLIC_KEY_DER_BYTES = 91
PUBLIC_KEY_TEXT_LENGTH = 122
MAX_ECDSA_DER_SIGNATURE_BYTES = 72
KEY_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
PUBLIC_KEY_PATTERN = re.compile(rf"^[A-Za-z0-9_-]{{{PUBLIC_KEY_TEXT_LENGTH}}}$")
SIGNATURE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
DEFAULT_DEVICE_KEY_PATH = Path(Paths.persist_root()) / "comma/navassist/device_key.pem"
PAIRED_APP_PARAM = "NavAssistPairedApp"
DEVICE_PRIVATE_KEY_PARAM = "NavAssistDevicePrivateKey"
PAIRED_APP_VERSION = 2
MAX_PAIRED_APPS = 4


def _base64url_encode(value: bytes) -> str:
  return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
  if not isinstance(value, str) or "=" in value:
    raise ValueError("base64url value must be unpadded text")
  return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _public_key_der(public_key: ec.EllipticCurvePublicKey) -> bytes:
  if not isinstance(public_key.curve, ec.SECP256R1):
    raise ValueError("NavAssist identity must use P-256")
  encoded = public_key.public_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
  )
  if len(encoded) != PUBLIC_KEY_DER_BYTES:
    raise ValueError("unexpected P-256 public-key encoding")
  return encoded


def encode_public_key(public_key: ec.EllipticCurvePublicKey) -> str:
  return _base64url_encode(_public_key_der(public_key))


def public_key_id(public_key_text: str) -> str:
  public_key = decode_public_key(public_key_text)
  return hashlib.sha256(_public_key_der(public_key)).digest()[:16].hex()


def decode_public_key(public_key_text: str) -> ec.EllipticCurvePublicKey:
  if not isinstance(public_key_text, str) or PUBLIC_KEY_PATTERN.fullmatch(public_key_text) is None:
    raise ValueError("invalid P-256 public-key encoding")
  try:
    encoded = _base64url_decode(public_key_text)
    public_key = serialization.load_der_public_key(encoded)
  except (TypeError, UnsupportedAlgorithm, ValueError) as error:
    raise ValueError("invalid P-256 public key") from error
  if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(public_key.curve, ec.SECP256R1):
    raise ValueError("NavAssist identity must use P-256")
  if _public_key_der(public_key) != encoded:
    raise ValueError("public-key encoding must be canonical")
  return public_key


def _decode_signature(signature: str) -> bytes:
  if not isinstance(signature, str) or SIGNATURE_PATTERN.fullmatch(signature) is None:
    raise ValueError("invalid ECDSA signature encoding")
  try:
    decoded = _base64url_decode(signature)
  except (ValueError, base64.binascii.Error) as error:
    raise ValueError("invalid ECDSA signature encoding") from error
  if not 0 < len(decoded) <= MAX_ECDSA_DER_SIGNATURE_BYTES:
    raise ValueError("invalid ECDSA signature size")
  return decoded


def verify_signature(public_key_text: str, material: bytes, signature: str) -> bool:
  try:
    public_key = decode_public_key(public_key_text)
    public_key.verify(_decode_signature(signature), material, ec.ECDSA(hashes.SHA256()))
  except (InvalidSignature, TypeError, UnsupportedAlgorithm, ValueError):
    return False
  return True


@dataclass(frozen=True)
class NavAssistDeviceIdentity:
  _private_key: ec.EllipticCurvePrivateKey
  public_key: str
  device_id: str

  @classmethod
  def load_or_create(cls, path: str | Path = DEFAULT_DEVICE_KEY_PATH, *, params: Any | None = None) -> NavAssistDeviceIdentity:
    if params is not None:
      stored = params.get(DEVICE_PRIVATE_KEY_PARAM)
      if stored is None:
        private_key = ec.generate_private_key(ec.SECP256R1())
        payload = private_key.private_bytes(
          encoding=serialization.Encoding.PEM,
          format=serialization.PrivateFormat.PKCS8,
          encryption_algorithm=serialization.NoEncryption(),
        )
        try:
          params.put(DEVICE_PRIVATE_KEY_PARAM, payload.decode("ascii"), block=True)
        except (OSError, RuntimeError) as error:
          raise RuntimeError("NavAssist device identity could not be persisted") from error
      else:
        try:
          payload = stored.encode("ascii") if isinstance(stored, str) else bytes(stored)
          private_key = serialization.load_pem_private_key(payload, password=None)
        except (UnicodeEncodeError, TypeError, UnsupportedAlgorithm, ValueError) as error:
          raise RuntimeError("NavAssist device identity is unreadable") from error
      if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(private_key.curve, ec.SECP256R1):
        raise RuntimeError("NavAssist device identity is not a P-256 key")
      public_key = encode_public_key(private_key.public_key())
      return cls(private_key, public_key, public_key_id(public_key))

    key_path = Path(path)
    if key_path.exists():
      try:
        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
      except (OSError, TypeError, UnsupportedAlgorithm, ValueError) as error:
        raise RuntimeError("NavAssist device identity is unreadable") from error
      if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(private_key.curve, ec.SECP256R1):
        raise RuntimeError("NavAssist device identity is not a P-256 key")
    else:
      private_key = ec.generate_private_key(ec.SECP256R1())
      payload = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
      )
      key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
      try:
        key_path.parent.chmod(0o700)
      except OSError as error:
        raise RuntimeError("NavAssist identity directory permissions could not be secured") from error
      temporary = key_path.with_name(f".{key_path.name}.{os.getpid()}.tmp")
      try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as key_file:
          key_file.write(payload)
          key_file.flush()
          os.fsync(key_file.fileno())
        os.replace(temporary, key_path)
      except OSError as error:
        try:
          temporary.unlink(missing_ok=True)
        except OSError:
          pass
        raise RuntimeError("NavAssist device identity could not be persisted") from error

    try:
      key_path.chmod(0o600)
    except OSError as error:
      raise RuntimeError("NavAssist device identity permissions could not be secured") from error
    public_key = encode_public_key(private_key.public_key())
    return cls(private_key, public_key, public_key_id(public_key))

  def sign(self, material: bytes) -> str:
    if not isinstance(material, bytes):
      raise TypeError("signature material must be bytes")
    signature = self._private_key.sign(material, ec.ECDSA(hashes.SHA256()))
    if len(signature) > MAX_ECDSA_DER_SIGNATURE_BYTES:
      raise RuntimeError("P-256 signature exceeded its DER bound")
    return _base64url_encode(signature)


@dataclass(frozen=True)
class PairedApp:
  key_id: str
  public_key: str


class NavAssistPairingStore:
  """Owns the bounded set of phone identities trusted to publish navigation snapshots."""

  def __init__(self, params: Any):
    self._params = params
    self._lock = threading.Lock()
    self._paired = self._load(params.get(PAIRED_APP_PARAM))

  @staticmethod
  def _load(value: Any) -> tuple[PairedApp, ...]:
    if value is None:
      return ()
    if not isinstance(value, dict):
      raise RuntimeError("NavAssist paired app identity is unreadable")
    if type(value.get("version")) is not int:
      raise RuntimeError("NavAssist paired app identity is unreadable")

    if set(value) == {"version", "keyId", "publicKey"} and value.get("version") == 1:
      raw_apps = [{"keyId": value["keyId"], "publicKey": value["publicKey"]}]
    elif set(value) == {"version", "apps"} and value.get("version") == PAIRED_APP_VERSION:
      raw_apps = value["apps"]
    else:
      raise RuntimeError("NavAssist paired app identity is unreadable")

    if not isinstance(raw_apps, list) or not 0 < len(raw_apps) <= MAX_PAIRED_APPS:
      raise RuntimeError("NavAssist paired app identity is unreadable")
    paired: list[PairedApp] = []
    try:
      for raw in raw_apps:
        if not isinstance(raw, dict) or set(raw) != {"keyId", "publicKey"}:
          raise ValueError
        key_id = raw["keyId"]
        public_key = raw["publicKey"]
        if (not isinstance(key_id, str) or KEY_ID_PATTERN.fullmatch(key_id) is None
            or not isinstance(public_key, str) or public_key_id(public_key) != key_id):
          raise ValueError
        paired.append(PairedApp(key_id, public_key))
    except ValueError:
      raise RuntimeError("NavAssist paired app identity is unreadable") from None
    if len({app.key_id for app in paired}) != len(paired):
      raise RuntimeError("NavAssist paired app identity is unreadable")
    return tuple(paired)

  def authorize_or_pair(self, key_id: str, public_key: str, *, is_offroad: bool) -> bool:
    try:
      if KEY_ID_PATTERN.fullmatch(key_id) is None or public_key_id(public_key) != key_id:
        return False
    except (TypeError, ValueError):
      return False

    with self._lock:
      if any(app.key_id == key_id and app.public_key == public_key for app in self._paired):
        return True
      if not is_offroad:
        return False
      if len(self._paired) >= MAX_PAIRED_APPS:
        return False
      paired = (*self._paired, PairedApp(key_id, public_key))
      record = {
        "version": PAIRED_APP_VERSION,
        "apps": [{"keyId": app.key_id, "publicKey": app.public_key} for app in paired],
      }
      try:
        self._params.put(PAIRED_APP_PARAM, record, block=True)
      except (OSError, RuntimeError) as error:
        raise RuntimeError("NavAssist paired app identity could not be persisted") from error
      self._paired = paired
      return True

  def public_key_for(self, key_id: str) -> str | None:
    with self._lock:
      return next((app.public_key for app in self._paired if app.key_id == key_id), None)

  def reset(self) -> None:
    with self._lock:
      self._params.remove(PAIRED_APP_PARAM)
      self._paired = ()
