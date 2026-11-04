"""Thin client for OpenRouter's OpenAI-compatible chat completions API.

One service owns all provider configuration: the three feature models are
selected here from environment variables, never hardcoded in the routers.

Privacy note: the default free models explicitly prohibit submitting
confidential or personal data. This configuration is for synthetic/demo
studies only — see README's AI privacy section.
"""

import os
import re
from typing import List, Optional

import httpx

DEFAULT_CHAT_MODEL = "nvidia/nemotron-3.5-lightning:free"
DEFAULT_ADVICE_MODEL = "nvidia/nemotron-3.5-lightning:free"
DEFAULT_VISION_MODEL = "nvidia/nemotron-3.5-super-vl:free"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

# Generation budgets, measured live against OpenRouter. The configured NVIDIA
# models are reasoning models: they emit hidden chain-of-thought tokens that
# count against max_tokens *before* any answer text appears, so the small
# budgets carried over from the previous non-reasoning provider left the answer
# empty. Observed completion totals: chat ~700, advice ~4100, vision ~550 tokens
# — these leave headroom so a reply is never cut off mid-sentence.
CHAT_MAX_TOKENS = 2000
ADVICE_MAX_TOKENS = 8000
VISION_MAX_TOKENS = 2000

# The read window has to cover a full reasoning pass: advice at ADVICE_MAX_TOKENS
# measured ~48 s live. Connect stays short so a dead network fails fast on an
# interactive UI action instead of hanging.
_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class OpenRouterError(Exception):
    pass


# Whitelisted, not free text: callers pass this straight into a system prompt,
# so it must never be arbitrary client-supplied text (a prompt-injection
# vector). Only an exact match is used; anything else is silently ignored.
SUPPORTED_LANGUAGES = {"Hindi", "Tamil", "Malayalam", "Telugu"}


def language_instruction(language: Optional[str]) -> str:
    if language not in SUPPORTED_LANGUAGES:
        return ""
    return (
        "\n\nRespond in {}, written in {} script, regardless of what language "
        "the user or the data is in."
    ).format(language, language)


def api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "")


def base_url() -> str:
    return os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def chat_model() -> str:
    return os.environ.get("OPENROUTER_CHAT_MODEL", DEFAULT_CHAT_MODEL)


def advice_model() -> str:
    return os.environ.get("OPENROUTER_ADVICE_MODEL", DEFAULT_ADVICE_MODEL)


def vision_model() -> str:
    return os.environ.get("OPENROUTER_VISION_MODEL", DEFAULT_VISION_MODEL)


# Frontend-safe messages: keyed on status, never echo the upstream body, which
# could carry provider internals (and must never carry our key).
_STATUS_MESSAGES = {
    401: "The AI provider rejected the configured API key. Check OPENROUTER_API_KEY.",
    402: "The AI provider reports insufficient credits for this request.",
    429: "The AI provider's rate limit was reached. Wait a moment and try again.",
}


def _error_for_status(status_code: int) -> str:
    if status_code in _STATUS_MESSAGES:
        return _STATUS_MESSAGES[status_code]
    if status_code >= 500:
        return "The AI provider or upstream model is unavailable right now. Try again later."
    return "The AI provider rejected the request (status {}).".format(status_code)


def chat(messages: List[dict], model: Optional[str] = None, max_tokens: Optional[int] = None, temperature: float = 0.5) -> str:
    key = api_key()
    if not key:
        raise OpenRouterError("OPENROUTER_API_KEY is not configured.")

    headers = {
        "Authorization": "Bearer {}".format(key),
        "Content-Type": "application/json",
    }
    # Optional OpenRouter attribution headers, only sent when configured.
    referer = os.environ.get("OPENROUTER_REFERER")
    title = os.environ.get("OPENROUTER_TITLE")
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-OpenRouter-Title"] = title

    try:
        resp = httpx.post(
            "{}/chat/completions".format(base_url()),
            headers=headers,
            json={
                "model": model or chat_model(),
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens or CHAT_MAX_TOKENS,
            },
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException as e:
        raise OpenRouterError("The AI provider did not respond in time. Try again.") from e
    except httpx.HTTPError as e:
        raise OpenRouterError("Could not reach the AI provider.") from e

    if resp.status_code >= 400:
        raise OpenRouterError(_error_for_status(resp.status_code))

    try:
        data = resp.json()
    except ValueError as e:
        raise OpenRouterError("The AI provider returned an unreadable response.") from e
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise OpenRouterError("Unexpected response shape from the AI provider.") from e
    # A reasoning model that runs out of budget returns a partial answer (or none
    # at all) with finish_reason "length". Serving half a sentence of dietary
    # guidance as if it were complete is worse than an explicit failure, so this
    # is surfaced rather than passed through.
    if choice.get("finish_reason") == "length":
        raise OpenRouterError(
            "The AI provider's reply was cut off before it finished (the model's "
            "reasoning used up its token budget). Try again, or raise the "
            "max_tokens budget for this model."
        )
    if not isinstance(content, str) or not content.strip():
        raise OpenRouterError("The AI provider returned an empty response.")
    return content.strip()


def strip_markdown(text: str) -> str:
    """Models don't always honour a plain-text instruction; clean up what leaks through."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*\d+\.\s+", "- ", text)
    text = re.sub(r"(?m)^\s*\*\s+", "- ", text)
    return text.strip()
