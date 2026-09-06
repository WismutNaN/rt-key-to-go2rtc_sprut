"""Generate one static SprutHub MQTT template containing all access points."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from rtkey_gateway.domain import AccessBinding
from rtkey_gateway.errors import ValidationError


_TOPIC_PREFIX_RE = re.compile(r"^[a-z0-9][a-z0-9/_-]{0,127}$")
_TEMPLATE_FILENAME_RE = re.compile(r"^rtkey_access_[0-9a-f]{8}\.json$")


@dataclass(frozen=True, slots=True)
class SprutHubAccessEntry:
    mqtt_key: str
    display_name: str


@dataclass(frozen=True, slots=True)
class SprutHubAccessTemplate:
    entries: tuple[SprutHubAccessEntry, ...]
    display_name: str
    filename: str
    content: bytes


def _validated_topic_prefix(value: str) -> str:
    prefix = value.strip().rstrip("/").lower()
    if not _TOPIC_PREFIX_RE.fullmatch(prefix) or "//" in prefix:
        raise ValidationError("MQTT topic prefix is not safe for a SprutHub template")
    return prefix


def _display_names(bindings: tuple[AccessBinding, ...]) -> dict[str, str]:
    title_counts = Counter(binding.point.title.casefold() for binding in bindings)
    names: dict[str, str] = {}
    for binding in bindings:
        title = binding.point.title
        if title_counts[title.casefold()] > 1:
            stable_id = binding.mqtt_key.value.rsplit("_", 1)[-1]
            title = f"{title} [{stable_id}]"
        names[binding.mqtt_key.value] = title
    return names


def _aggregate_display_name(entries: tuple[SprutHubAccessEntry, ...]) -> str:
    full_name = " | ".join(entry.display_name for entry in entries)
    if len(full_name) <= 512:
        return full_name
    digest = hashlib.sha256(full_name.encode("utf-8")).hexdigest()[:10]
    suffix = f" ... [{len(entries)}:{digest}]"
    return full_name[: 512 - len(suffix)].rstrip(" |") + suffix


def build_spruthub_access_template(
    bindings: Iterable[AccessBinding],
    topic_prefix: str,
) -> SprutHubAccessTemplate | None:
    """Build one device containing one exact-topic switch per access point."""
    prefix = _validated_topic_prefix(topic_prefix)
    present = tuple(
        sorted(
            (binding for binding in bindings if binding.present),
            key=lambda binding: binding.mqtt_key.value,
        )
    )
    mqtt_keys = [binding.mqtt_key.value for binding in present]
    if len(mqtt_keys) != len(set(mqtt_keys)):
        raise ValidationError("Access state contains duplicate MQTT device keys")
    display_names = _display_names(present)
    if not present:
        return None
    entries = tuple(
        sorted(
            (
                SprutHubAccessEntry(
                    mqtt_key=binding.mqtt_key.value,
                    display_name=display_names[binding.mqtt_key.value],
                )
                for binding in present
            ),
            key=lambda entry: (entry.display_name.casefold(), entry.mqtt_key),
        )
    )
    aggregate_name = _aggregate_display_name(entries)
    services = []
    for entry in entries:
        topic_base = f"{prefix}/access/{entry.mqtt_key}"
        services.append(
            {
                "name": entry.display_name,
                "type": "Switch",
                "characteristics": [
                    {
                        "type": "On",
                        "link": [
                            {
                                "type": "String",
                                "topicGet": f"{topic_base}/state",
                                "topicSet": f"{topic_base}/set",
                                "map": {"false": "OFF", "true": "ON"},
                            }
                        ],
                    }
                ],
            }
        )

    document = {
        "name": aggregate_name,
        "manufacturer": aggregate_name,
        "model": aggregate_name,
        "modelIds": [f"{prefix}/access/catalog"],
        "services": services,
    }
    content = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    content_id = hashlib.sha256(content).hexdigest()[:8]
    return SprutHubAccessTemplate(
        entries=entries,
        display_name=aggregate_name,
        filename=f"rtkey_access_{content_id}.json",
        content=content,
    )


def build_spruthub_template_archive(
    templates: Iterable[SprutHubAccessTemplate],
) -> bytes:
    """Return a deterministic, path-safe tar archive for extraction on the host."""
    items = tuple(templates)
    filenames = [template.filename for template in items]
    if len(filenames) != len(set(filenames)) or any(
        not _TEMPLATE_FILENAME_RE.fullmatch(filename) for filename in filenames
    ):
        raise ValidationError("SprutHub template archive contains an unsafe filename")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for template in items:
            info = tarfile.TarInfo(template.filename)
            info.size = len(template.content)
            info.mode = 0o644
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(template.content))
    return output.getvalue()
