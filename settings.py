"""Ajustes de generación que llegan desde la barra lateral o el entorno."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class GenerationSettings:
    use_llm: bool = False
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    tts_engine: str = "gtts"

    @property
    def key(self) -> str:
        return (self.api_key or os.environ.get("OPENAI_API_KEY") or "").strip()

    @property
    def url(self) -> str:
        explicit = (self.base_url or os.environ.get("OPENAI_BASE_URL") or "").strip()
        return explicit or "https://api.openai.com/v1"

    @property
    def model_name(self) -> str:
        return (self.model or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
