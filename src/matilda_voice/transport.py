from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class TransportConfig:
    transport: str
    endpoint: str | None
    host: str
    port: int


def resolve(transport_env: str, endpoint_env: str, host: str, port: int) -> TransportConfig:
    transport = os.getenv(transport_env, "tcp").strip().lower() or "tcp"
    endpoint = os.getenv(endpoint_env)
    return TransportConfig(transport=transport, endpoint=endpoint, host=host, port=port)
