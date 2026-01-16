from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str
    code: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    error: ErrorDetail


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    service: Optional[str] = None


class SpeakResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    voice: Optional[str] = None


class SpeakResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    result: SpeakResult


class SynthesizeResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    audio: str
    format: str
    text: str
    size_bytes: int


class SynthesizeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    result: SynthesizeResult


class ProvidersResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    providers: List[str]


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    result: ProvidersResult


class ReloadResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str


class ReloadResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    result: ReloadResult
