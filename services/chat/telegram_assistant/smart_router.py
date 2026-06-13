"""
smart_router.py — Smart content classifier for LegasVex Premium.

Автоматически определяет контур обработки:
  - 'confidential' → конфиденциальный контур (Mac mini, локальная модель)
  - 'expert'       → экспертный контур (облачная модель или Mac mini с cloud LLM)

Пользователь видит только тип задачи, а не технические детали маршрутизации.
"""
from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Ключевые слова для классификации (расширяемы через .env)
# -----------------------------------------------------------------------

_CONFIDENTIAL_KEYWORDS: list[str] = [
    # Персональные данные
    "персональные данные", "паспорт", "снилс", "инн",
    "адрес проживания", "место жительства",
    # Профессиональная тайна
    "адвокатская тайна", "нотариальная тайна", "конфиденциально",
    "доверитель", "нотариус",
    # Личная жизнь
    "частная жизнь", "медицинская", "медицинские данные",
    # Договорная чувствительность
    "коммерческая тайна", "банковская тайна",
]

_EXPERT_KEYWORDS: list[str] = [
    # Стратегия
    "стратегия защиты", "правовая позиция", "линия защиты",
    "тактика", "апелляция", "кассация", "надзорная жалоба",
    # Аналитика
    "судебная практика", "прецедент", "консилиум", "совет адвокатов",
    "анализ рисков", "вероятность", "оценка перспектив",
    "арбитраж", "третейский", "международный суд",
    # Сложные задачи
    "сравнительный анализ", "доктрина", "юрисдикция",
]

# Типы файлов → route
_DOCUMENT_TYPES_CONFIDENTIAL = {".pdf", ".docx", ".doc", ".xlsx", ".xls"}
_DOCUMENT_TYPES_EXPERT = {".txt", ".md", ".json"}

# TaskType → route mapping
_TASKTYPE_CONFIDENTIAL = {
    "document_final", "client_intake", "document_draft",
    "case_create", "case_update",
}
_TASKTYPE_EXPERT = {
    "legal_analysis", "research", "complaint_prep", "risk_review",
}


@dataclass
class RouteDecision:
    route: str          # 'confidential' | 'expert'
    reason: str         # Причина в логах (не показывается пользователю)
    confidence: float   # 0.0 – 1.0


def classify_route(
    text: str = "",
    task_type: str = "",
    has_document: bool = False,
    file_extension: str = "",
) -> RouteDecision:
    """
    Classify a request into a processing route.

    Priority:
      1. Explicit confidential keywords → confidential
      2. Document types → confidential (default for docs)
      3. Explicit expert keywords → expert
      4. TaskType mapping
      5. Default → confidential (safest)
    """
    text_lower = text.lower()
    task_lower = task_type.lower()
    ext = file_extension.lower()

    # -- Load extra keywords from .env (if configured) --
    extra_conf = os.getenv("LEGASVEX_ROUTE_CONFIDENTIAL_KEYWORDS", "")
    extra_expert = os.getenv("LEGASVEX_ROUTE_EXPERT_KEYWORDS", "")

    conf_kw = _CONFIDENTIAL_KEYWORDS + [k.strip() for k in extra_conf.split(",") if k.strip()]
    expert_kw = _EXPERT_KEYWORDS + [k.strip() for k in extra_expert.split(",") if k.strip()]

    # 1. Confidential keywords
    for kw in conf_kw:
        if kw in text_lower:
            return RouteDecision(
                route="confidential",
                reason=f"keyword '{kw}' in text",
                confidence=0.95,
            )

    # 2. Document extension
    if has_document or ext:
        if ext in _DOCUMENT_TYPES_CONFIDENTIAL or (has_document and not ext):
            return RouteDecision(
                route="confidential",
                reason=f"document type '{ext or 'unknown'}' → confidential by default",
                confidence=0.85,
            )
        if ext in _DOCUMENT_TYPES_EXPERT:
            return RouteDecision(
                route="expert",
                reason=f"document type '{ext}' → expert",
                confidence=0.70,
            )

    # 3. Expert keywords
    expert_score = sum(1 for kw in expert_kw if kw in text_lower)
    if expert_score >= 2:
        return RouteDecision(
            route="expert",
            reason=f"{expert_score} expert keywords matched",
            confidence=min(0.6 + expert_score * 0.1, 0.95),
        )
    if expert_score == 1:
        # Single expert keyword → expert only if task_type also expert
        matched_kw = next(kw for kw in expert_kw if kw in text_lower)
        if task_lower in _TASKTYPE_EXPERT:
            return RouteDecision(
                route="expert",
                reason=f"expert keyword + expert task_type",
                confidence=0.75,
            )

    # 4. TaskType mapping
    if task_lower in _TASKTYPE_CONFIDENTIAL:
        return RouteDecision(
            route="confidential",
            reason=f"task_type '{task_type}' → confidential",
            confidence=0.80,
        )
    if task_lower in _TASKTYPE_EXPERT:
        return RouteDecision(
            route="expert",
            reason=f"task_type '{task_type}' → expert",
            confidence=0.75,
        )

    # 5. Default: confidential (safe)
    return RouteDecision(
        route="confidential",
        reason="default route (no strong signal)",
        confidence=0.60,
    )


def route_to_compute_mode(route: str, allow_cloud_llm: bool = False) -> str:
    """
    Maps a route decision to a compute mode.

    Returns 'mac_mini' or 'vps_ai'.
    'expert' route prefers cloud (vps_ai) if cloud LLM is allowed.
    """
    if route == "expert" and allow_cloud_llm:
        return "vps_ai"
    return "mac_mini"
