"""
dashboard.py — Premium welcome screen data provider.

Собирает статистику для главного экрана без технических деталей.
Всё рассчитывается быстро (SQLite only), без сетевых вызовов.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client_store import ClientStore

logger = logging.getLogger(__name__)


def get_welcome_data(chat_id: str, store: "ClientStore") -> dict:
    """
    Returns a dict with data for the Premium welcome screen:
        active_matter_id : str | None   — last opened matter ID
        system_ready     : bool         — True (always True on call; caller checks LLM separately)
        today_new        : int          — new handoffs today
        today_pending    : int          — handoffs awaiting approval
        today_approved   : int          — handoffs approved today
        total_cases      : int          — total cases for this chat_id
    """
    result = {
        "active_matter_id": None,
        "system_ready": True,
        "today_new": 0,
        "today_pending": 0,
        "today_approved": 0,
        "total_cases": 0,
    }
    try:
        import sqlite3
        from datetime import date

        today = date.today().isoformat()

        with sqlite3.connect(store.path) as conn:
            conn.row_factory = sqlite3.Row

            # Total cases
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM cases WHERE chat_id=?",
                (str(chat_id),),
            ).fetchone()
            if row:
                result["total_cases"] = row["cnt"]

            # Most recent case as "active matter"
            row = conn.execute(
                "SELECT id FROM cases WHERE chat_id=? ORDER BY created_at DESC LIMIT 1",
                (str(chat_id),),
            ).fetchone()
            if row:
                result["active_matter_id"] = f"CASE-{row['id']}"

            # Today's handoff stats
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS cnt
                FROM handoffs
                WHERE chat_id=? AND date(created_at)=?
                GROUP BY status
                """,
                (str(chat_id), today),
            ).fetchall()
            for row in rows:
                if row["status"] == "pending":
                    result["today_pending"] += row["cnt"]
                elif row["status"] == "approved":
                    result["today_approved"] += row["cnt"]
                else:
                    result["today_new"] += row["cnt"]

    except Exception as exc:  # noqa: BLE001
        logger.warning("dashboard.get_welcome_data error: %s", exc)

    return result


def format_welcome_message(data: dict, advocate_name: str | None = None) -> str:
    """
    Formats the Premium welcome screen text from get_welcome_data() output.

    Example output:
        ⚖️ LEGASVEX PREMIUM

        Добро пожаловать, Алексей.

        Активное дело: MAT-2026-0042
        Статус системы: 🟢 Готова к работе

        Сегодня:
        • Новых материалов: 3
        • На проверке: 1
        • Согласовано: 2
    """
    lines: list[str] = ["⚖️ *LEGASVEX PREMIUM*", ""]

    greeting = "Добро пожаловать"
    if advocate_name:
        greeting += f", {advocate_name}"
    lines.append(greeting + ".")
    lines.append("")

    if data.get("active_matter_id"):
        lines.append(f"Активное дело: `{data['active_matter_id']}`")
    else:
        lines.append("Активных дел пока нет.")

    status_icon = "🟢" if data.get("system_ready") else "🟡"
    lines.append(f"Статус системы: {status_icon} Готова к работе")
    lines.append("")

    total = data.get("total_cases", 0)
    new_ = data.get("today_new", 0)
    pending = data.get("today_pending", 0)
    approved = data.get("today_approved", 0)

    if total > 0 or new_ > 0 or pending > 0 or approved > 0:
        lines.append("Сегодня:")
        if new_ > 0:
            lines.append(f"• Новых материалов: {new_}")
        if pending > 0:
            lines.append(f"• На проверке: {pending}")
        if approved > 0:
            lines.append(f"• Согласовано: {approved}")
        if new_ == 0 and pending == 0 and approved == 0:
            lines.append("• Активности нет")
    else:
        lines.append("Начните с описания правовой ситуации.")

    return "\n".join(lines)
