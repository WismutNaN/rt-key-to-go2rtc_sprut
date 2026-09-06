"""Generate one static SprutHub MQTT template per access point."""

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
_TEMPLATE_FILENAME_RE = re.compile(
    r"^rtkey_[a-z0-9][a-z0-9_-]{0,63}_[0-9a-f]{8}\.json$"
)


@dataclass(frozen=True, slots=True)
class SprutHubAccessTemplate:
    mqtt_key: str
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


def build_spruthub_access_templates(
    bindings: Iterable[AccessBinding],
    topic_prefix: str,
) -> tuple[SprutHubAccessTemplate, ...]:
    """Build exact-topic templates with location names in every visible label."""
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
    result: list[SprutHubAccessTemplate] = []

    for binding in present:
        mqtt_key = binding.mqtt_key.value
        display_name = display_names[mqtt_key]
        topic_base = f"{prefix}/access/{mqtt_key}"
        document = {
            "name": display_name,
            "manufacturer": display_name,
            "model": display_name,
            "modelIds": [f"{topic_base}/state"],
            "services": [
                {
                    "name": display_name,
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
            ],
        }
        content = (
            json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        content_id = hashlib.sha256(content).hexdigest()[:8]
        filename = f"rtkey_{mqtt_key}_{content_id}.json"
        result.append(
            SprutHubAccessTemplate(
                mqtt_key=mqtt_key,
                display_name=display_name,
                filename=filename,
                content=content,
            )
        )

    return tuple(result)


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
