"""Versioned atomic JSON repository for Access Control state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from rtkey_gateway.domain import (
    AccessBinding,
    AccessPoint,
    AccessPointId,
    AccessPointKind,
    AccessState,
    MqttDeviceKey,
)
from rtkey_gateway.errors import StateError, ValidationError


class JsonAccessStateRepository:
    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")

    @staticmethod
    def _optional_int(data: dict[str, object], key: str) -> int | None:
        value = data.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValidationError(f"Access state field {key} must be a positive integer")
        return value

    @staticmethod
    def _binding_to_dict(binding: AccessBinding) -> dict[str, object]:
        return {
            "point_id": binding.point.point_id.value,
            "kind": binding.point.kind.value,
            "title": binding.point.title,
            "camera_id": binding.point.camera_id,
            "mqtt_key": binding.mqtt_key.value,
            "present": binding.present,
        }

    @staticmethod
    def _binding_from_dict(payload: object) -> AccessBinding:
        if not isinstance(payload, dict):
            raise ValidationError("Access state binding is not an object")
        present = payload.get("present", False)
        if not isinstance(present, bool):
            raise ValidationError("Access state present flag is not a boolean")
        try:
            kind = AccessPointKind(str(payload["kind"]))
        except (KeyError, ValueError) as exc:
            raise ValidationError("Access state kind is unsupported") from exc
        camera_id = payload.get("camera_id")
        return AccessBinding(
            point=AccessPoint(
                point_id=AccessPointId(str(payload["point_id"])),
                kind=kind,
                title=str(payload.get("title") or ""),
                camera_id=str(camera_id) if camera_id is not None else None,
            ),
            mqtt_key=MqttDeviceKey(str(payload["mqtt_key"])),
            present=present,
        )

    def _decode(self, raw: str) -> AccessState:
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValidationError("Access state root is not an object")
            version = payload.get("schema_version", 0)
            if version != self.SCHEMA_VERSION or isinstance(version, bool):
                raise ValidationError(f"Unsupported access state schema version {version}")
            raw_bindings = payload.get("bindings", {})
            if not isinstance(raw_bindings, dict):
                raise ValidationError("Access state bindings is not an object")
            bindings: dict[str, AccessBinding] = {}
            mqtt_keys: set[str] = set()
            for raw_identity, raw_binding in raw_bindings.items():
                binding = self._binding_from_dict(raw_binding)
                identity = str(raw_identity)
                if binding.identity != identity:
                    raise ValidationError("Access state key does not match device identity")
                if binding.mqtt_key.value in mqtt_keys:
                    raise ValidationError("Access state contains duplicate MQTT keys")
                bindings[identity] = binding
                mqtt_keys.add(binding.mqtt_key.value)
            authentication_failed = payload.get("authentication_failed", False)
            if not isinstance(authentication_failed, bool):
                raise ValidationError(
                    "Access state authentication_failed flag is not a boolean"
                )
            return AccessState(
                schema_version=version,
                bindings=bindings,
                last_fetch_at=self._optional_int(payload, "last_fetch_at"),
                last_success_at=self._optional_int(payload, "last_success_at"),
                last_error=(
                    str(payload["last_error"]) if payload.get("last_error") else None
                ),
                authentication_failed=authentication_failed,
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            raise StateError(
                "Access state file is invalid or uses an unsupported schema"
            ) from exc

    def load(self) -> AccessState:
        if not self.path.exists() and not self.backup_path.exists():
            return AccessState()
        errors: list[OSError | StateError] = []
        for candidate in (self.path, self.backup_path):
            try:
                return self._decode(candidate.read_text(encoding="utf-8"))
            except (OSError, StateError) as exc:
                errors.append(exc)
        raise StateError("Neither primary nor backup access state can be loaded") from errors[-1]

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

    def save(self, state: AccessState) -> None:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "bindings": {
                identity: self._binding_to_dict(binding)
                for identity, binding in sorted(state.bindings.items())
            },
            "last_fetch_at": state.last_fetch_at,
            "last_success_at": state.last_success_at,
            "last_error": state.last_error,
            "authentication_failed": state.authentication_failed,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.", dir=self.path.parent
            )
            backup_temporary: str | None = None
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                if self.path.exists():
                    try:
                        self._decode(self.path.read_text(encoding="utf-8"))
                    except (OSError, StateError):
                        pass
                    else:
                        backup_fd, backup_temporary = tempfile.mkstemp(
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
                        os.chmod(backup_temporary, 0o600)
                        os.replace(backup_temporary, self.backup_path)
                        backup_temporary = None
                os.replace(temporary, self.path)
                self._fsync_directory(self.path.parent)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
                if backup_temporary and os.path.exists(backup_temporary):
                    os.unlink(backup_temporary)
        except OSError as exc:
            raise StateError("Could not save access state atomically") from exc

    def sanitized(self) -> dict[str, object]:
        state = self.load()
        return {
            "enabled": True,
            "last_fetch_at": state.last_fetch_at,
            "last_success_at": state.last_success_at,
            "last_error": state.last_error,
            "authentication_failed": state.authentication_failed,
            "devices": [
                {
                    "device_id": binding.point.point_id.value,
                    "kind": binding.point.kind.value,
                    "title": binding.point.title,
                    "camera_id": binding.point.camera_id,
                    "mqtt_key": binding.mqtt_key.value,
                    "present": binding.present,
                }
                for binding in sorted(
                    state.bindings.values(), key=lambda item: item.mqtt_key.value
                )
            ],
        }
