from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    error: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    service: Optional[str] = None


class SpeakResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    success: bool
    text: str
    voice: Optional[str] = None


class SynthesizeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    success: bool
    audio: str
    format: str
    text: str
    size_bytes: int


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    providers: List[str]


class ReloadResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    message: str
