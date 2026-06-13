"""AI-powered legal assistant for LegasVex Advocates.

Provider priority:
  1. Ollama (local, LEGASVEX_LOCAL_LLM_ENDPOINT set) — preferred, no cost
  2. OpenRouter (LEGASVEX_ALLOW_CLOUD_LLM=true + OPENROUTER_API_KEY set)
  3. None → caller falls back to structured templates

All outputs are internal lawyer drafts — never direct client delivery.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SYSTEM_PROMPT = """Ты — AI-ассистент адвокатской практики LegasVex Advocates.
Работаешь ТОЛЬКО с адвокатами и юридической командой. Доверитель не получает твои ответы напрямую.

Твоя задача: подготовить ЧЕРНОВИК рабочего плана адвоката.

ОБЯЗАТЕЛЬНО для каждого ответа:
1. Краткий анализ правовой ситуации (2-3 предложения)
2. Применимые нормы права (ГК РФ, ТК РФ, ГПК РФ и т.д.)
3. Ключевые вопросы к доверителю (3-5 вопросов)
4. Предварительная стратегия (2-3 варианта)
5. Критические сроки и процессуальные риски

ОГРАНИЧЕНИЯ:
- Это черновик для адвоката, не финальная консультация
- Не давай категоричных правовых заключений без документов
- Всегда требуй проверки фактов и документов адвокатом
- Не рекомендуй конкретные действия без изучения материалов дела

Отвечай на русском, структурированно, профессионально."""

_CONTINUATION_PROMPT = """Ты — AI-ассистент адвокатской практики.
Адвокат описал дополнительные детали ситуации. Дай развёрнутый черновой анализ:
1. Уточнённая правовая квалификация
2. Применимые нормы по новым данным
3. Рекомендуемый следующий шаг
4. Необходимые документы

Это черновик для внутреннего использования адвоката. Отвечай по-русски."""


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _ollama_config() -> tuple[str, str]:
    """Return (endpoint, model). endpoint is empty when Ollama not configured."""
    endpoint = os.getenv("LEGASVEX_LOCAL_LLM_ENDPOINT", "").strip()
    model = os.getenv(
        "LEGASVEX_LLM_MODEL_DEFAULT",
        os.getenv("LEGASVEX_LOCAL_LLM_MODEL", "qwen2.5:7b"),
    ).strip()
    return endpoint, model


def _openrouter_config() -> tuple[str, str, bool]:
    """Return (api_key, model, allowed)."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv(
        "LEGASVEX_OPENROUTER_MODEL_MAIN",
        os.getenv("LEGASVEX_OPENROUTER_MODEL_DEFAULT", "google/gemini-2.0-flash-001"),
    ).strip()
    allowed = os.getenv("LEGASVEX_ALLOW_CLOUD_LLM", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }
    return api_key, model, allowed


def is_ai_available() -> bool:
    """Return True when any real AI provider is reachable."""
    endpoint, _ = _ollama_config()
    if endpoint:
        return True
    api_key, _, allowed = _openrouter_config()
    return allowed and bool(api_key)


def active_provider() -> str:
    """Return name of the active provider: 'ollama', 'openrouter', or 'none'."""
    endpoint, _ = _ollama_config()
    if endpoint:
        return "ollama"
    api_key, _, allowed = _openrouter_config()
    if allowed and api_key:
        return "openrouter"
    return "none"


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

def _call_ollama(system: str, user: str) -> str | None:
    endpoint, model = _ollama_config()
    if not endpoint:
        return None
    url = f"{endpoint.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["message"]["content"]
    except (urllib.error.URLError, KeyError, TypeError, json.JSONDecodeError, TimeoutError):
        return None


# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------

def _call_openrouter(system: str, user: str) -> str | None:
    api_key, model, allowed = _openrouter_config()
    if not allowed or not api_key:
        return None
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 1200,
        "temperature": 0.3,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _OPENROUTER_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://legasvex.ai",
            "X-Title": "LegasVex Advocates",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _call_llm(system: str, user: str) -> str | None:
    """Try Ollama first, then OpenRouter. Return raw output or None."""
    result = _call_ollama(system, user)
    if result:
        return result
    return _call_openrouter(system, user)


def ai_legal_analysis(topic: str, context: str = "") -> str | None:
    """Return AI analysis of a legal topic, or None if AI unavailable.

    Args:
        topic: The legal situation described by the advocate.
        context: Optional extra context (prior messages, clarifications).

    Returns:
        Formatted draft analysis string, or None on failure/unavailability.
    """
    user_content = topic.strip()
    if context.strip():
        user_content = f"{context.strip()}\n\nНовая информация: {user_content}"

    output = _call_llm(_SYSTEM_PROMPT, user_content)
    if output:
        return output.strip()
    return None


def ai_continuation(topic: str, clarification: str) -> str | None:
    """Return AI continuation/clarification analysis, or None if unavailable."""
    user_content = f"Исходная ситуация: {topic}\n\nУточнение: {clarification}"
    output = _call_llm(_CONTINUATION_PROMPT, user_content)
    if output:
        return output.strip()
    return None
