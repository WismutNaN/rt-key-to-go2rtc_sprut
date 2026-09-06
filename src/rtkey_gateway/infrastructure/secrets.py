"""Secret sources that can be replaced without changing application code."""

from __future__ import annotations

from pathlib import Path

from rtkey_gateway.errors import AuthenticationError


class FileAccessTokenSource:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> str:
        try:
            token = self.path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise AuthenticationError(
                "Bearer token file is missing or unreadable"
            ) from exc
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token or any(char.isspace() for char in token):
            raise AuthenticationError("Bearer token file contains an invalid value")
        return token
