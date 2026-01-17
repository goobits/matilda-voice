from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str
    code: str
    retryable: bool


class EnvelopeBase(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str
    service: str
    task: str
    result: Optional[object] = None
    error: Optional[ErrorDetail] = None


class SpeakResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    voice: Optional[str] = None


class SpeakResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    result: SpeakResult


class SynthesizeResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    audio: str
    format: str
    text: str
    size_bytes: int


class SynthesizeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    result: SynthesizeResult


class ProvidersResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    providers: List[str]


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    result: ProvidersResult


class ReloadResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str


class ReloadResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    result: ReloadResult


class SpeakEnvelope(EnvelopeBase):
    result: SpeakResult


class SynthesizeEnvelope(EnvelopeBase):
    result: SynthesizeResult


class ProvidersEnvelope(EnvelopeBase):
    result: ProvidersResult


class ReloadEnvelope(EnvelopeBase):
    result: ReloadResult


class ErrorEnvelope(EnvelopeBase):
    error: ErrorDetail
