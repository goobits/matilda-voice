from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class SpeakRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    voice: Optional[str] = None
    provider: Optional[str] = None


class SynthesizeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    voice: Optional[str] = None
    provider: Optional[str] = None
    format: Optional[str] = None
