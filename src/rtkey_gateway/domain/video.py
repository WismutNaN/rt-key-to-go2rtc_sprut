"""Domain entities and naming policy for stable public camera streams."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Iterable

from rtkey_gateway.domain.media import MediaProfile
from rtkey_gateway.errors import ValidationError


_STREAM_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_NON_NAME_RE = re.compile(r"[^a-z0-9]+")
_CYRILLIC = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
        "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
        "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
        "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch",
        "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya", "№": " ",
    }
)


def _clean_title(value: object, fallback: str) -> str:
    title = "".join(
        char
        for char in str(value)
        if not unicodedata.category(char).startswith("C")
    )
    return (" ".join(title.split()) or fallback)[:512]


@dataclass(frozen=True, slots=True)
class CameraId:
    value: str

    def __post_init__(self) -> None:
        normalized = str(self.value).strip()
        if not normalized or len(normalized) > 256:
            raise ValidationError("Camera ID must be non-empty and at most 256 chars")
        if any(
            char.isspace() or unicodedata.category(char).startswith("C")
            for char in normalized
        ):
            raise ValidationError("Camera ID must not contain whitespace or controls")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class StreamName:
    value: str

    def __post_init__(self) -> None:
        normalized = str(self.value).strip().lower()
        if not _STREAM_NAME_RE.fullmatch(normalized):
            raise ValidationError(
                "Stream name must match [a-z0-9][a-z0-9_-]{0,63}"
            )
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, repr=False)
class SecretUrl:
    value: str

    def __post_init__(self) -> None:
        value = str(self.value).strip()
        if not value:
            raise ValidationError("Secret URL must be non-empty")
        if any(unicodedata.category(char).startswith("C") for char in value):
            raise ValidationError("Secret URL must not contain control characters")
        object.__setattr__(self, "value", value)

    def __repr__(self) -> str:
        return "SecretUrl('***')"

    def __str__(self) -> str:
        return "***"


@dataclass(frozen=True, slots=True)
class CameraFeed:
    camera_id: CameraId
    title: str
    upstream_url: SecretUrl
    expires_at: int | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "title", _clean_title(self.title, f"Camera {self.camera_id.value[:8]}")
        )
        if self.expires_at is not None and self.expires_at <= 0:
            object.__setattr__(self, "expires_at", None)


@dataclass(frozen=True, slots=True)
class CameraBinding:
    camera_id: CameraId
    stream_name: StreamName
    title: str
    present: bool = True
    last_good_upstream: SecretUrl | None = field(default=None, repr=False)
    last_good_profile: MediaProfile | None = None
    last_good_expires_at: int | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "title", _clean_title(self.title, f"Camera {self.camera_id.value[:8]}")
        )


@dataclass(frozen=True, slots=True)
class GatewayState:
    schema_version: int = 1
    bindings: dict[str, CameraBinding] = field(default_factory=dict)
    last_fetch_at: int | None = None
    last_success_at: int | None = None
    last_error: str | None = None
    authentication_failed: bool = False

    def with_bindings(self, bindings: dict[str, CameraBinding]) -> "GatewayState":
        return replace(self, bindings=bindings)


class StreamNamingPolicy:
    """Assign readable names once and preserve them across API reordering."""

    @staticmethod
    def slug_from_title(title: str) -> str:
        text = str(title).strip().lower().translate(_CYRILLIC)
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
        return _NON_NAME_RE.sub("_", text).strip("_")[:64]

    @staticmethod
    def _uid_suffix(camera_id: CameraId) -> str:
        safe = re.sub(r"[^a-z0-9]", "", camera_id.value.lower())
        return (safe[:8] or "unknown").ljust(8, "0")

    def reconcile(
        self, state: GatewayState, feeds: Iterable[CameraFeed]
    ) -> GatewayState:
        bindings = {
            uid: replace(binding, present=False)
            for uid, binding in state.bindings.items()
        }
        used = {binding.stream_name.value for binding in bindings.values()}

        for feed in sorted(feeds, key=lambda item: item.camera_id.value):
            uid = feed.camera_id.value
            current = bindings.get(uid)
            if current is not None:
                bindings[uid] = replace(current, title=feed.title, present=True)
                continue

            base = self.slug_from_title(feed.title)
            suffix = self._uid_suffix(feed.camera_id)
            if not base:
                candidate = f"camera_{suffix}"
            elif base not in used:
                candidate = base
            else:
                candidate = f"{base[:55].rstrip('_')}_{suffix}"

            counter = 2
            unique = candidate
            while unique in used:
                tail = f"_{suffix}_{counter}"
                unique = f"{candidate[:64 - len(tail)].rstrip('_')}{tail}"
                counter += 1

            name = StreamName(unique)
            used.add(name.value)
            bindings[uid] = CameraBinding(
                camera_id=feed.camera_id,
                stream_name=name,
                title=feed.title,
            )

        return state.with_bindings(bindings)
