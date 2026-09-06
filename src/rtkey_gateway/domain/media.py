"""Media policy that can evolve independently from providers and gateways."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from rtkey_gateway.errors import ValidationError


class AudioMode(str, Enum):
    COPY = "copy"
    AAC = "aac"
    PCMA = "pcma"
    PCMU = "pcmu"
    NONE = "none"

    @classmethod
    def parse(cls, value: str) -> "AudioMode":
        try:
            return cls(value.strip().lower())
        except (AttributeError, ValueError) as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValidationError(
                f"Unsupported audio mode {value!r}; expected one of: {allowed}"
            ) from exc


@dataclass(frozen=True, slots=True)
class MediaProfile:
    """Codec choices exposed to a media gateway adapter."""

    audio_mode: AudioMode = AudioMode.COPY
    video_mode: str = "copy"

    def __post_init__(self) -> None:
        if self.video_mode != "copy":
            raise ValidationError("Video transcoding is outside the v1 scope")


@dataclass(frozen=True, slots=True)
class AudioPolicy:
    """Resolve a global mode with optional per-camera overrides."""

    default: AudioMode = AudioMode.COPY
    overrides: Mapping[str, AudioMode] = field(default_factory=dict)

    def profile_for(self, camera_id: str) -> MediaProfile:
        return MediaProfile(audio_mode=self.overrides.get(camera_id, self.default))
