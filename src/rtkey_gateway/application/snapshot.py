"""Application query for an authenticated on-demand camera snapshot."""

from __future__ import annotations

from rtkey_gateway.application.ports import SnapshotGatewayPort, VideoStateRepository
from rtkey_gateway.domain import MediaPolicy, StreamName
from rtkey_gateway.errors import ValidationError


class GetCameraSnapshot:
    def __init__(
        self,
        repository: VideoStateRepository,
        snapshot_gateway: SnapshotGatewayPort,
        media_policy: MediaPolicy,
    ) -> None:
        self.repository = repository
        self.snapshot_gateway = snapshot_gateway
        self.media_policy = media_policy

    def execute(self, raw_stream_name: str) -> bytes:
        stream_name = StreamName(raw_stream_name)
        state = self.repository.load()
        binding = None
        for item in state.bindings.values():
            if not item.present or item.last_good_upstream is None:
                continue
            for variant in self.media_policy.variants_for(
                item.camera_id.value,
                base_profile=item.last_good_profile,
            ):
                if (
                    variant.stream_name_value(item.stream_name.value)
                    == stream_name.value
                ):
                    binding = item
                    break
            if binding is not None:
                break
        if binding is None or binding.last_good_upstream is None:
            raise ValidationError("Snapshot stream is unknown or not verified")
        return self.snapshot_gateway.fetch_jpeg(stream_name)
