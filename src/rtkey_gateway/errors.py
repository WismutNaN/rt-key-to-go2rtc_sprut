"""Typed errors shared by application ports and infrastructure adapters."""


class GatewayError(RuntimeError):
    """Base error safe to classify without inspecting third-party exceptions."""


class AuthenticationError(GatewayError):
    """The configured Bearer token is unavailable, invalid or rejected."""


class TransportError(GatewayError):
    """A remote service could not be reached or returned an HTTP error."""


class SchemaError(GatewayError):
    """An external response no longer matches a supported schema."""


class ValidationError(GatewayError):
    """Configuration or external data violates a local invariant."""


class MediaGatewayError(GatewayError):
    """go2rtc did not accept or expose a stream update."""


class StateError(GatewayError):
    """Persistent state could not be loaded or saved safely."""
