from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def build_message_log_path(project_root: Path, ts: datetime | None = None) -> Path:
    current = ts or datetime.now(timezone.utc)
    return project_root / "data" / "telegram_messages" / f"messages_{current.strftime('%Y-%m-%d')}.jsonl"


def build_message_id_reply(chat_id: str, message_id: int | str, sender_id: str = "", direction: str = "") -> str:
    lines = [
        "Telegram IDs",
        f"chat_id: {chat_id}",
        f"message_id: {message_id}",
    ]
    if sender_id:
        lines.append(f"sender_id: {sender_id}")
    if direction:
        lines.append(f"direction: {direction}")
    return "\n".join(lines)


def append_message_log(project_root: Path, record: dict, ts: datetime | None = None) -> Path:
    path = build_message_log_path(project_root, ts=ts)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "logged_at": (ts or datetime.now(timezone.utc)).isoformat(),
        **record,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def text_preview(text: str, limit: int = 240) -> str:
    normalized = " ".join((text or "").split())
    return normalized[:limit]
