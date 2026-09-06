from __future__ import annotations

import base64
import json
from dataclasses import replace

from rtkey_gateway.domain import GatewayState
from rtkey_gateway.infrastructure.http import HttpResponse


def jwt_with_exp(exp: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": exp}).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.signature"


class QueueTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str, dict[str, str]]] = []

    def request(self, method, url, *, headers=None, timeout=20.0):  # noqa: ANN001
        self.requests.append((method, url, dict(headers or {})))
        if not self.responses:
            raise AssertionError(f"Unexpected HTTP request: {method} {url}")
        return self.responses.pop(0)


def json_response(payload: object, status: int = 200) -> HttpResponse:
    return HttpResponse(status, json.dumps(payload).encode(), {})


class MemoryRepository:
    def __init__(self, state: GatewayState | None = None) -> None:
        self.state = state or GatewayState()
        self.saved: list[GatewayState] = []

    def load(self) -> GatewayState:
        return self.state

    def save(self, state: GatewayState) -> None:
        self.state = state
        self.saved.append(state)


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def time(self) -> float:
        return self.now
