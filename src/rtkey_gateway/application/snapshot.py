"""Application query for an authenticated on-demand camera snapshot."""

from __future__ import annotations

from rtkey_gateway.application.ports import SnapshotGatewayPort, VideoStateRepository
from rtkey_gateway.domain import StreamName
from rtkey_gateway.errors import ValidationError


class GetCameraSnapshot:
    def __init__(
        self,
        repository: VideoStateRepository,
        snapshot_gateway: SnapshotGatewayPort,
    ) -> None:
        self.repository = repository
        self.snapshot_gateway = snapshot_gateway

    def execute(self, raw_stream_name: str) -> bytes:
        stream_name = StreamName(raw_stream_name)
        state = self.repository.load()
        binding = next(
            (
                item
                for item in state.bindings.values()
                if item.present and item.stream_name == stream_name
            ),
            None,
        )
        if binding is None or binding.last_good_upstream is None:
            raise ValidationError("Snapshot stream is unknown or not verified")
        return self.snapshot_gateway.fetch_jpeg(stream_name)
