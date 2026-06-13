"""
transparency.py — Premium transparency footer generator.

После каждого ответа генерирует компактную карточку:
что сделано, каким контуром, какой моделью.
Никаких технических терминов.
"""
from __future__ import annotations

# Метки для пользователя (не технические названия)
_ROUTE_LABELS = {
    "confidential": "🔒 Конфиденциальный",
    "expert": "🚀 Экспертный",
    "local": "🔒 Конфиденциальный",   # backward compat
    "mac_mini": "🔒 Конфиденциальный",
    "vps_ai": "🚀 Экспертный",
}

_MODEL_LABELS = {
    "local": "Локальная",
    "ollama": "Локальная",
    "cloud": "Облачная",
    "openrouter": "Облачная",
    "rule_based": "Правила",
    "dry_run": "Упрощённый режим",
    "unknown": "—",
}

_COUNCIL_MODE_LABELS = {
    "quick": "Быстрый (2 роли)",
    "standard": "Стандартный (4 роли)",
    "full": "Полный консилиум (8 ролей)",
}


def build_footer(
    matter_id: str | None = None,
    judge_used: bool = False,
    council_used: bool = False,
    council_mode: str | None = None,
    sources_checked: bool = False,
    route: str = "confidential",
    model: str = "unknown",
    duration_sec: int | None = None,
) -> str:
    """
    Build a compact transparency footer.

    Example output:
        ─────────────────
        📄 Материал: MAT-2026-0042
        ⚖️ Совет адвокатов: Да (Стандартный · 4 роли)
        📚 Практика: Проверено
        🧠 Контур: 🔒 Конфиденциальный · Локальная модель
        ─────────────────
        Черновик для адвоката. Проверьте перед использованием.
    """
    sep = "─" * 25
    lines: list[str] = [sep]

    if matter_id:
        lines.append(f"📄 Материал: `{matter_id}`")

    if council_used:
        mode_label = _COUNCIL_MODE_LABELS.get(council_mode or "standard", "")
        council_line = "⚖️ Совет адвокатов: Да"
        if mode_label:
            council_line += f" ({mode_label})"
        if duration_sec:
            council_line += f" · {duration_sec} сек"
        lines.append(council_line)

    if judge_used:
        lines.append("👨‍⚖️ Оценка судьёй: Выполнена")

    if sources_checked:
        lines.append("📚 Практика: Проверено")

    route_label = _ROUTE_LABELS.get(route, route)
    model_label = _MODEL_LABELS.get(model, model)
    lines.append(f"🧠 Контур: {route_label} · {model_label}")

    lines.append(sep)
    lines.append("_Черновик для адвоката. Проверьте перед использованием._")

    return "\n".join(lines)


def build_dry_run_notice() -> str:
    """Уведомление когда анализ выполнен без LLM (dry_run)."""
    return (
        "⚠️ *Анализ выполнен в упрощённом режиме.*\n"
        "Локальная модель временно недоступна.\n"
        "Результат основан на правилах и шаблонах — без ИИ-рассуждений.\n"
        "Для полного анализа повторите запрос позже."
    )


def build_mode_switched_notice(new_route: str) -> str:
    """Уведомление после смены контура."""
    label = _ROUTE_LABELS.get(new_route, new_route)
    return f"✅ Переключено на {label} контур."
