"""Versioned, atomic JSON repository for Video Gateway state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from rtkey_gateway.domain import (
    AudioMode,
    CameraBinding,
    CameraId,
    GatewayState,
    MediaProfile,
    SecretUrl,
    StreamName,
    VideoMode,
)
from rtkey_gateway.errors import StateError, ValidationError


class JsonVideoStateRepository:
    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)

    @staticmethod
    def _optional_int(data: dict[str, object], key: str) -> int | None:
        value = data.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(f"State field {key} is not an integer")
        if value <= 0:
            raise ValidationError(f"State field {key} must be positive")
        return value

    @staticmethod
    def _binding_to_dict(binding: CameraBinding) -> dict[str, object]:
        return {
            "camera_id": binding.camera_id.value,
            "stream_name": binding.stream_name.value,
            "title": binding.title,
            "present": binding.present,
            "last_good_upstream": (
                binding.last_good_upstream.value
                if binding.last_good_upstream is not None
                else None
            ),
            "last_good_profile": (
                {
                    "video_mode": binding.last_good_profile.video_mode.value,
                    "video_fps": binding.last_good_profile.video_fps,
                    "audio_mode": binding.last_good_profile.audio_mode.value,
                }
                if binding.last_good_profile is not None
                else None
            ),
            "last_good_expires_at": binding.last_good_expires_at,
            "last_error": binding.last_error,
        }

    @staticmethod
    def _binding_from_dict(data: object) -> CameraBinding:
        if not isinstance(data, dict):
            raise ValidationError("State binding is not an object")
        present = data.get("present", False)
        if not isinstance(present, bool):
            raise ValidationError("State binding present flag is not a boolean")
        upstream = data.get("last_good_upstream")
        raw_profile = data.get("last_good_profile")
        if raw_profile is not None and not isinstance(raw_profile, dict):
            raise ValidationError("State media profile is not an object")
        profile = (
            MediaProfile(
                audio_mode=AudioMode.parse(str(raw_profile.get("audio_mode", "copy"))),
                video_mode=VideoMode.parse(str(raw_profile.get("video_mode", "copy"))),
                video_fps=int(raw_profile.get("video_fps", 30)),
            )
            if raw_profile is not None
            else None
        )
        return CameraBinding(
            camera_id=CameraId(str(data["camera_id"])),
            stream_name=StreamName(str(data["stream_name"])),
            title=str(data.get("title") or "Camera"),
            present=present,
            last_good_upstream=SecretUrl(str(upstream)) if upstream else None,
            last_good_profile=profile,
            last_good_expires_at=JsonVideoStateRepository._optional_int(
                data, "last_good_expires_at"
            ),
            last_error=str(data["last_error"]) if data.get("last_error") else None,
        )

    def _decode(self, raw: str) -> GatewayState:
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValidationError("State root is not an object")
            version = payload.get("schema_version", 0)
            if isinstance(version, bool) or not isinstance(version, int):
                raise ValidationError("State schema version is not an integer")
            if version != self.SCHEMA_VERSION:
                raise ValidationError(f"Unsupported state schema version {version}")
            raw_bindings = payload.get("bindings", {})
            if not isinstance(raw_bindings, dict):
                raise ValidationError("State bindings is not an object")
            bindings: dict[str, CameraBinding] = {}
            stream_names: set[str] = set()
            for raw_uid, raw_binding in raw_bindings.items():
                uid = str(raw_uid)
                binding = self._binding_from_dict(raw_binding)
                if binding.camera_id.value != uid:
                    raise ValidationError("State binding key does not match camera ID")
                if binding.stream_name.value in stream_names:
                    raise ValidationError("State contains duplicate stream names")
                bindings[uid] = binding
                stream_names.add(binding.stream_name.value)
            authentication_failed = payload.get("authentication_failed", False)
            if not isinstance(authentication_failed, bool):
                raise ValidationError(
                    "State authentication_failed flag is not a boolean"
                )
            return GatewayState(
                schema_version=version,
                bindings=bindings,
                last_fetch_at=self._optional_int(payload, "last_fetch_at"),
                last_success_at=self._optional_int(payload, "last_success_at"),
                last_error=str(payload["last_error"]) if payload.get("last_error") else None,
                authentication_failed=authentication_failed,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            raise StateError("State file is invalid or uses an unsupported schema") from exc

    def load(self) -> GatewayState:
        if not self.path.exists() and not self.backup_path.exists():
            return GatewayState()
        errors: list[OSError | StateError] = []
        for candidate in (self.path, self.backup_path):
            try:
                return self._decode(candidate.read_text(encoding="utf-8"))
            except (OSError, StateError) as exc:
                errors.append(exc)
        raise StateError("Neither primary nor backup state can be loaded") from errors[-1]

    def save(self, state: GatewayState) -> None:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "bindings": {
                uid: self._binding_to_dict(binding)
                for uid, binding in sorted(state.bindings.items())
            },
            "last_fetch_at": state.last_fetch_at,
            "last_success_at": state.last_success_at,
            "last_error": state.last_error,
            "authentication_failed": state.authentication_failed,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", dir=self.path.parent
            )
            backup_temp_name: str | None = None
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temp_name, 0o600)
                if self.path.exists():
                    try:
                        self._decode(self.path.read_text(encoding="utf-8"))
                    except (OSError, StateError):
                        pass
                    else:
                        backup_fd, backup_temp_name = tempfile.mkstemp(
                            prefix=f".{self.backup_path.name}.",
                            dir=self.path.parent,
                        )
                        with os.fdopen(backup_fd, "wb") as backup, self.path.open(
                            "rb"
                        ) as source:
                            while chunk := source.read(64 * 1024):
                                backup.write(chunk)
                            backup.flush()
                            os.fsync(backup.fileno())
                        os.chmod(backup_temp_name, 0o600)
                        os.replace(backup_temp_name, self.backup_path)
                        backup_temp_name = None
                os.replace(temp_name, self.path)
                self._fsync_directory(self.path.parent)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
                if backup_temp_name and os.path.exists(backup_temp_name):
                    os.unlink(backup_temp_name)
        except OSError as exc:
            raise StateError("Could not save gateway state atomically") from exc

    def sanitized(self) -> dict[str, object]:
        state = self.load()
        return {
            "schema_version": state.schema_version,
            "last_fetch_at": state.last_fetch_at,
            "last_success_at": state.last_success_at,
            "last_error": state.last_error,
            "authentication_failed": state.authentication_failed,
            "cameras": [
                {
                    "camera_id": binding.camera_id.value,
                    "stream_name": binding.stream_name.value,
                    "title": binding.title,
                    "present": binding.present,
                    "expires_at": binding.last_good_expires_at,
                    "error": binding.last_error,
                }
                for binding in sorted(
                    state.bindings.values(), key=lambda item: item.stream_name.value
                )
            ],
        }
