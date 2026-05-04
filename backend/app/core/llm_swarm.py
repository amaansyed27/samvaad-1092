"""
LLM Swarm — Model-Agnostic Provider Factory & Cascade Engine
===============================================================
Implements the SovereignProvider abstraction and cascade routing:

    ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
    │  GroqCloud   │ ──▶ │  Gemini 3    │ ──▶ │  DeepSeek    │
    │  (fast path) │     │   Flash      │     │ (deep parse) │
    └──────────────┘     └──────────────┘     └──────────────┘
         │ <500ms             │ 500ms-2s           │ deep analysis
         ▼                    ▼                    ▼
      Sentiment           Sentiment +          Cultural nuance,
      extraction          Analysis             dialect parsing

Cascade Logic:
    1. Groq/Flash for sub-500ms sentiment extraction
    2. DeepSeek via OpenRouter for deep dialect & cultural nuance
    3. Any provider can be hot-swapped at runtime

SECURITY: All inputs MUST be pre-scrubbed by PIIScrubber.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import settings
from app.models import CascadeEntry

logger = logging.getLogger("samvaad.llm_swarm")


# ══════════════════════════════════════════════════════════════════════════════
# Abstract Base — SovereignProvider
# ══════════════════════════════════════════════════════════════════════════════

class SovereignProvider(abc.ABC):
    """
    Abstract base for all LLM providers.

    Every provider must implement `generate()` — a single async method
    that accepts a system prompt and user message and returns the model's
    text response.

    The factory (`ProviderFactory`) selects providers at runtime based on
    purpose, latency budgets, and availability.
    """

    name: str = "base"
    model: str = ""

    @abc.abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        """Generate a text completion. Must be implemented by subclasses."""
        ...

    async def health_check(self) -> bool:
        """Quick liveness check. Override for custom probes."""
        try:
            await self.generate("Reply with OK", "health", max_tokens=5)
            return True
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════════════════
# Concrete Providers
# ══════════════════════════════════════════════════════════════════════════════

class GeminiProvider(SovereignProvider):
    """Google Gemini via the google-genai SDK."""

    name = "gemini"

    def __init__(self) -> None:
        self.model = settings.gemini_model
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=settings.gemini_api_key)

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        self._ensure_client()
        loop = asyncio.get_running_loop()

        def _call():
            from google.genai import types
            response = self._client.models.generate_content(
                model=self.model,
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            return response.text

        return await loop.run_in_executor(None, _call)


class GroqProvider(SovereignProvider):
    """GroqCloud — ultra-low-latency inference."""

    name = "groq"

    def __init__(self) -> None:
        self.model = settings.groq_model
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from groq import Groq
            self._client = Groq(api_key=settings.groq_api_key)

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        self._ensure_client()
        loop = asyncio.get_running_loop()

        def _call():
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content

        return await loop.run_in_executor(None, _call)


class DeepSeekProvider(SovereignProvider):
    """DeepSeek direct API — deep dialect & cultural nuance parsing."""

    name = "deepseek"

    def __init__(self) -> None:
        self.model = settings.deepseek_model
        self._http = httpx.AsyncClient(
            base_url="https://api.deepseek.com",
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
            },
            timeout=30.0,
        )

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = await self._http.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

class OpenRouterProvider(SovereignProvider):
    """OpenRouter — fallback for diverse model access."""

    name = "openrouter"

    def __init__(self, model_override: str | None = None) -> None:
        self.model = model_override or settings.openrouter_model
        self._http = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "HTTP-Referer": "https://samvaad1092.gov.in",
                "X-Title": "Samvaad 1092",
            },
            timeout=30.0,
        )

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = await self._http.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# ══════════════════════════════════════════════════════════════════════════════
# Provider Factory & Cascade Engine
# ══════════════════════════════════════════════════════════════════════════════

class ProviderFactory:
    """
    Hot-swappable provider registry with cascade execution.

    Usage:
        factory = ProviderFactory()
        result, log = await factory.cascade_generate(
            system_prompt="...",
            user_message="...",
            purpose="sentiment",
            providers=["groq", "gemini"],  # try Groq first, fallback to Gemini
        )
    """

    def __init__(self) -> None:
        self._providers: dict[str, SovereignProvider] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register all configured providers."""
        if settings.groq_api_key:
            self._providers["groq"] = GroqProvider()
        if settings.gemini_api_key:
            self._providers["gemini"] = GeminiProvider()
        if settings.openrouter_api_key:
            self._providers["openrouter"] = OpenRouterProvider()
            # Redundant OpenRouter instances
            self._providers["or-hy3"] = OpenRouterProvider("tencent/hy3-preview:free")
            self._providers["or-oss-120b"] = OpenRouterProvider("openai/gpt-oss-120b:free")
            self._providers["or-nano"] = OpenRouterProvider("nvidia/nemotron-3-nano-30b-a3b:free")
        if settings.deepseek_api_key:
            self._providers["deepseek"] = DeepSeekProvider()
        logger.info(
            "ProviderFactory initialised with: %s",
            list(self._providers.keys()),
        )

    def register(self, name: str, provider: SovereignProvider) -> None:
        """Hot-register a new provider at runtime."""
        self._providers[name] = provider
        logger.info("Provider registered: %s", name)

    def get(self, name: str) -> SovereignProvider | None:
        return self._providers.get(name)

    @property
    def available(self) -> list[str]:
        return list(self._providers.keys())

    async def cascade_generate(
        self,
        system_prompt: str,
        user_message: str,
        *,
        purpose: str = "analysis",
        providers: list[str] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> tuple[str, list[CascadeEntry]]:
        """
        Try providers in order. Return the first successful result.

        Parameters
        ----------
        purpose : str
            "sentiment" | "analysis" | "restatement" — used for logging
        providers : list[str]
            Ordered list of provider names to try. Defaults to all available.

        Returns
        -------
        (response_text, cascade_log)
        """
        names = providers or self.available
        cascade_log: list[CascadeEntry] = []

        for name in names:
            provider = self._providers.get(name)
            if provider is None:
                continue

            start = time.perf_counter()
            try:
                result = await provider.generate(
                    system_prompt,
                    user_message,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                latency = (time.perf_counter() - start) * 1000
                cascade_log.append(
                    CascadeEntry(
                        provider=name,
                        model=provider.model,
                        purpose=purpose,
                        latency_ms=round(latency, 1),
                        success=True,
                    )
                )
                logger.info(
                    "Cascade [%s] %s succeeded in %.0fms",
                    purpose,
                    name,
                    latency,
                )
                return result, cascade_log

            except Exception as exc:
                latency = (time.perf_counter() - start) * 1000
                cascade_log.append(
                    CascadeEntry(
                        provider=name,
                        model=provider.model,
                        purpose=purpose,
                        latency_ms=round(latency, 1),
                        success=False,
                        error=str(exc),
                    )
                )
                logger.warning(
                    "Cascade [%s] %s failed in %.0fms: %s",
                    purpose,
                    name,
                    latency,
                    exc,
                )

        raise RuntimeError(
            f"All providers failed for purpose={purpose}. "
            f"Tried: {names}. Log: {cascade_log}"
        )


# Singleton
_factory: ProviderFactory | None = None


def get_factory() -> ProviderFactory:
    """Singleton factory accessor."""
    global _factory
    if _factory is None:
        _factory = ProviderFactory()
    return _factory
