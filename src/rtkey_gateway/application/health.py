"""Health evaluation separated from CLI and concrete infrastructure."""

from __future__ import annotations

from dataclasses import dataclass

from rtkey_gateway.domain import GatewayState


@dataclass(frozen=True, slots=True)
class HealthReport:
    healthy: bool
    degraded: bool
    messages: tuple[str, ...]


def evaluate_state(
    state: GatewayState,
    *,
    now: int,
    runtime_streams: set[str],
    max_stale: int,
    rtsp_reachable: bool,
    rtsp_streams: set[str] | frozenset[str] | None = None,
) -> HealthReport:
    errors: list[str] = []
    warnings: list[str] = []
    present = [binding for binding in state.bindings.values() if binding.present]

    if state.authentication_failed:
        errors.append("Bearer token rejected; replace it with manage.sh set-token")
    if state.last_fetch_at is None:
        errors.append("No successful camera discovery has completed")
    elif now - state.last_fetch_at > max_stale:
        warnings.append("Camera catalog data is stale")
    if not present:
        errors.append("No active cameras were discovered")
    if not rtsp_reachable:
        errors.append("go2rtc RTSP port is not reachable")

    for binding in present:
        if binding.stream_name.value not in runtime_streams:
            errors.append(f"Stream {binding.stream_name.value} is missing in go2rtc")
        elif (
            rtsp_streams is not None
            and binding.stream_name.value not in rtsp_streams
        ):
            errors.append(
                f"Stream {binding.stream_name.value} did not pass RTSP/upstream probe"
            )
        if (
            binding.last_good_expires_at is not None
            and binding.last_good_expires_at <= now
        ):
            errors.append(f"Stream {binding.stream_name.value} token is expired")
        if binding.last_error:
            warnings.append(f"Stream {binding.stream_name.value} is degraded")

    if state.last_error and not state.authentication_failed:
        warnings.append("The latest synchronization was not fully successful")
    return HealthReport(
        healthy=not errors,
        degraded=bool(warnings),
        messages=tuple(errors + warnings),
    )
