from __future__ import annotations

import asyncio
import json
import os
import ssl
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib import error, parse, request

from dotenv import load_dotenv

from .api_bridge import LocalAPIBridge
from .archive import build_archive_path, extract_document_text
from .assistant import LawyerTelegramAssistant
from .client_store import ClientStore
from .message_log import append_message_log, text_preview
from .ai_assistant import ai_continuation, ai_legal_analysis, is_ai_available
from .legal_search import search_legal_practice
from .pilot_matter_store import DRAFT_NOTICE, PilotMatterStore
from .dashboard import format_welcome_message, get_welcome_data
from .transparency import build_footer, build_dry_run_notice


COMPUTE_MODE_MAC = "mac_mini"
COMPUTE_MODE_VPS = "vps_ai"
_MAC_MINI_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
_VPS_HOST = "72.56.40.240"


def _check_host_reachable(host: str, port: int = 80, timeout: float = 2.5) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ROOT_ENV = Path(os.getenv("LEGASVEX_ENV_FILE") or (PROJECT_ROOT / ".env"))
WELCOME_TEXT = (
    "\u2696\ufe0f LegasVex Advocates\n\n"
    "\u0420\u0430\u0431\u043e\u0447\u0438\u0439 AI-\u043a\u043e\u043d\u0442\u0443\u0440 \u0430\u0434\u0432\u043e\u043a\u0430\u0442\u0441\u043a\u043e\u0439 \u043f\u0440\u0430\u043a\u0442\u0438\u043a\u0438.\n\n"
    "\u041e\u043f\u0438\u0448\u0438\u0442\u0435 \u0441\u0438\u0442\u0443\u0430\u0446\u0438\u044e \u2014 \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u0435 \u0447\u0435\u0440\u043d\u043e\u0432\u043e\u0439 \u043f\u043b\u0430\u043d: "
    "\u0430\u043d\u0430\u043b\u0438\u0437, \u0440\u0438\u0441\u043a\u0438, \u0432\u043e\u043f\u0440\u043e\u0441\u044b \u043a \u0434\u043e\u0432\u0435\u0440\u0438\u0442\u0435\u043b\u044e, \u043f\u0440\u043e\u0435\u043a\u0442 \u043f\u043e\u0437\u0438\u0446\u0438\u0438.\n\n"
    "\u0412\u0441\u0435 \u0432\u044b\u0432\u043e\u0434\u044b \u2014 \u0447\u0435\u0440\u043d\u043e\u0432\u0438\u043a\u0438 \u0434\u043b\u044f \u0430\u0434\u0432\u043e\u043a\u0430\u0442\u0430. \u0412\u043d\u0435\u0448\u043d\u044f\u044f \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0430 \u2014 \u0442\u043e\u043b\u044c\u043a\u043e \u043f\u043e\u0441\u043b\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438."
)
HELP_TEXT = (
    "\u2696\ufe0f \u041f\u043e\u043c\u043e\u0449\u044c\n\n"
    "/start \u2014 \u0433\u043b\u0430\u0432\u043d\u043e\u0435 \u043c\u0435\u043d\u044e\n"
    "/cases \u2014 \u043c\u043e\u0438 \u0434\u0435\u043b\u0430\n"
    "/history \u2014 \u0438\u0441\u0442\u043e\u0440\u0438\u044f \u0442\u0435\u043a\u0443\u0449\u0435\u0433\u043e \u0434\u0435\u043b\u0430\n"
    "/workspace \u2014 \u0440\u0430\u0431\u043e\u0447\u0435\u0435 \u043c\u0435\u0441\u0442\u043e\n\n"
    "\u041f\u0440\u0438\u043a\u0440\u0435\u043f\u0438\u0442\u0435 PDF, DOCX, TXT \u0438\u043b\u0438 \u0444\u043e\u0442\u043e \u043c\u0430\u0442\u0435\u0440\u0438\u0430\u043b\u043e\u0432 \u0434\u0435\u043b\u0430."
)
ACCESS_DENIED_TEXT = "Доступ ограничен. LegasVex Advocates является внутренним контуром адвокатской команды."


def parse_id_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


@dataclass(frozen=True)
class BotAccessPolicy:
    enforced: bool
    allowed_actor_ids: set[str]
    admin_actor_ids: set[str]
    allowed_chat_ids: set[str]
    assistant_actor_ids: set[str] = frozenset()
    practice_lead_actor_ids: set[str] = frozenset()

    @classmethod
    def from_env(cls) -> "BotAccessPolicy":
        return cls(
            enforced=os.getenv(
                "LEGASVEX_TELEGRAM_RBAC_ENABLED",
                os.getenv("LEGASVEX_TELEGRAM_RBAC_ENFORCED", "true"),
            ).strip().lower()
            in {"1", "true", "yes", "on"},
            allowed_actor_ids=parse_id_set(
                os.getenv("LEGASVEX_ALLOWED_TELEGRAM_IDS", os.getenv("LEGASVEX_TELEGRAM_ALLOWED_ACTOR_IDS", ""))
            ),
            admin_actor_ids=parse_id_set(os.getenv("LEGASVEX_TELEGRAM_ADMIN_ACTOR_IDS", "")),
            allowed_chat_ids=parse_id_set(os.getenv("LEGASVEX_TELEGRAM_ALLOWED_CHAT_IDS", "")),
            assistant_actor_ids=parse_id_set(os.getenv("LEGASVEX_TELEGRAM_ASSISTANT_ACTOR_IDS", "")),
            practice_lead_actor_ids=parse_id_set(os.getenv("LEGASVEX_TELEGRAM_PRACTICE_LEAD_ACTOR_IDS", "")),
        )

    def authorize(self, actor_id: str, chat_id: str) -> bool:
        if not self.enforced:
            return True
        actor_allowed = actor_id in (
            self.allowed_actor_ids
            | self.admin_actor_ids
            | self.assistant_actor_ids
            | self.practice_lead_actor_ids
        )
        chat_allowed = not self.allowed_chat_ids or chat_id in self.allowed_chat_ids
        return actor_allowed and chat_allowed

    def role_for(self, actor_id: str) -> str:
        if actor_id in self.admin_actor_ids:
            return "technical_operator"
        if actor_id in self.practice_lead_actor_ids:
            return "practice_lead"
        if actor_id in self.assistant_actor_ids:
            return "assistant"
        if actor_id in self.allowed_actor_ids:
            return "advocate_team"
        return "unauthorized"


def _make_ssl_context() -> ssl.SSLContext:
    """Return an SSL context compatible with Windows Python 3.12+."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        try:
            ctx.load_default_certs()
        except Exception:
            pass
    # Python 3.12 raises SSLEOFError when server closes TCP without TLS close_notify.
    # Telegram CDN and some proxies do this — suppress it.
    if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
        ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
    return ctx


class TelegramBotAPI:
    def __init__(self, token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.file_base_url = f"https://api.telegram.org/file/bot{token}"
        self._ssl_ctx = _make_ssl_context()

    def call(self, method: str, payload: dict | None = None, timeout: int = 40) -> dict:
        normalized = {
            key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            for key, value in (payload or {}).items()
            if value is not None
        }
        body = parse.urlencode(normalized).encode("utf-8")
        req = request.Request(f"{self.base_url}/{method}", data=body, method="POST")
        with request.urlopen(req, timeout=timeout, context=self._ssl_ctx) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(f"Telegram Bot API {method} failed")
        return result["result"]

    def download_file(self, file_id: str, target: Path) -> None:
        file_info = self.call("getFile", {"file_id": file_id})
        target.parent.mkdir(parents=True, exist_ok=True)
        with request.urlopen(
            f"{self.file_base_url}/{file_info['file_path']}", timeout=60, context=self._ssl_ctx
        ) as response:
            target.write_bytes(response.read())


def split_message(text: str, limit: int = 4000) -> list[str]:
    return [text[start : start + limit] for start in range(0, len(text), limit)] or [""]


def main_inline_keyboard(mode: str | None = None) -> dict:
    rows = []
    if mode == COMPUTE_MODE_MAC:
        rows.append([{"text": "\u0422\u0435\u043a\u0443\u0449\u0438\u0439 \u0440\u0435\u0436\u0438\u043c: \U0001f5a5 MAC MINI", "callback_data": "noop"}])
    elif mode == COMPUTE_MODE_VPS:
        rows.append([{"text": "\u0422\u0435\u043a\u0443\u0449\u0438\u0439 \u0440\u0435\u0436\u0438\u043c: \u2601\ufe0f VPS AI", "callback_data": "noop"}])
    rows.extend([
        [{"text": "\u2795 \u041d\u041e\u0412\u041e\u0415 \u0414\u0415\u041b\u041e", "callback_data": "ui:new_issue"}],
        [
            {"text": "\U0001f4c2 \u041c\u041e\u0418 \u0414\u0415\u041b\u0410", "callback_data": "ui:cases"},
            {"text": "\U0001f464 \u0420\u0410\u0411\u041e\u0427\u0415\u0415 \u041c\u0415\u0421\u0422\u041e", "callback_data": "ui:cabinet"},
        ],
        [
            {"text": "\U0001f500 \u0421\u041c\u0415\u041d\u0418\u0422\u042c \u0420\u0415\u0416\u0418\u041c", "callback_data": "ui:change_mode"},
            {"text": "\U0001f4ca \u0421\u0422\u0410\u0422\u0423\u0421 \u0421\u0418\u0421\u0422\u0415\u041c\u042b", "callback_data": "ui:system_status"},
        ],
        [{"text": "\u2753 \u041f\u041e\u041c\u041e\u0429\u042c", "callback_data": "ui:help"}],
        [{"text": "\U0001f504 \u041f\u0415\u0420\u0415\u0417\u0410\u041f\u0423\u0421\u041a \u0411\u041e\u0422\u0410", "callback_data": "ui:restart_confirm"}],
    ])
    return {"inline_keyboard": rows}


def mode_select_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "\U0001f512 \u041a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0439 \u043a\u043e\u043d\u0442\u0443\u0440", "callback_data": "ui:mode_mac_mini"},
                {"text": "\U0001f680 \u042d\u043a\u0441\u043f\u0435\u0440\u0442\u043d\u044b\u0439 \u0430\u043d\u0430\u043b\u0438\u0437", "callback_data": "ui:mode_vps_ai"},
            ]
        ]
    }


def sensitive_data_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "\U0001f512 \u041a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0439 \u043a\u043e\u043d\u0442\u0443\u0440", "callback_data": "ui:sensitive_mac"}],
            [{"text": "\U0001f680 \u042d\u043a\u0441\u043f\u0435\u0440\u0442\u043d\u044b\u0439 \u0430\u043d\u0430\u043b\u0438\u0437", "callback_data": "ui:sensitive_cloud"}],
            [{"text": "\u274c \u041e\u0442\u043c\u0435\u043d\u0430", "callback_data": "ui:sensitive_cancel"}],
        ]
    }


def consent_inline_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "✅ ПРИНЯТЬ И НАЧАТЬ", "callback_data": "ui:consent_accept"}],
        ]
    }


def contextual_inline_keyboard() -> dict:
    return {
        "inline_keyboard": [
            # ── Анализ ──────────────────────────────────
            [{"text": "\u2014\u2014\u2014 \U0001f4ca \u0410\u041d\u0410\u041b\u0418\u0417 \u2014\u2014\u2014", "callback_data": "noop"}],
            [
                {"text": "\U0001f4cb \u0410\u043d\u0430\u043b\u0438\u0437 \u0434\u0435\u043b\u0430", "callback_data": "tool:case_analysis"},
                {"text": "\u2696\ufe0f \u041f\u043e\u0437\u0438\u0446\u0438\u044f", "callback_data": "tool:legal_position"},
            ],
            [
                {"text": "\u26a0\ufe0f \u0420\u0438\u0441\u043a\u0438", "callback_data": "tool:risk_review"},
                {"text": "\U0001f50d \u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0438", "callback_data": "tool:source_check"},
            ],
            # ── Документы ───────────────────────────────
            [{"text": "\u2014\u2014\u2014 \U0001f4c4 \u0414\u041e\u041a\u0423\u041c\u0415\u041d\u0422\u042b \u2014\u2014\u2014", "callback_data": "noop"}],
            [
                {"text": "\U0001f4c4 \u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430", "callback_data": "tool:document_check"},
                {"text": "\U0001f4c3 \u0414\u043e\u0433\u043e\u0432\u043e\u0440", "callback_data": "ui:risk_scan"},
            ],
            [
                {"text": "\u2753 \u0412\u043e\u043f\u0440\u043e\u0441\u044b", "callback_data": "tool:questions_for_principal"},
                {"text": "\U0001f9fe \u0421\u0432\u043e\u0434\u043a\u0430", "callback_data": "tool:final_summary"},
            ],
            # ── Правовая тройка ──────────────────────────
            [{"text": "\u26a1 \u041f\u0420\u0410\u0412\u041e\u0412\u0410\u042f \u0422\u0420\u041e\u0419\u041a\u0410 \u26a1", "callback_data": "noop"}],
            [{"text": "\U0001f465 \u0421\u041e\u0412\u0415\u0422 \u0410\u0414\u0412\u041e\u041a\u0410\u0422\u041e\u0412", "callback_data": "tool:council"}],
            [
                {"text": "\U0001f3db\ufe0f \u0418\u0418 \u0421\u0423\u0414\u042c\u042f", "callback_data": "tool:judge_review"},
                {"text": "\u2696\ufe0f \u041f\u0440\u0430\u043a\u0442\u0438\u043a\u0430", "callback_data": "tool:legal_practice"},
            ],
            # ── Дело ─────────────────────────────────────
            [
                {"text": "\U0001f4be \u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c", "callback_data": "tool:save_to_matter"},
                {"text": "\u270f\ufe0f \u0423\u0442\u043e\u0447\u043d\u0438\u0442\u044c", "callback_data": "ui:clarify"},
            ],
            [
                {"text": "\U0001f468\u200d\u2696\ufe0f \u041f\u0435\u0440\u0435\u0434\u0430\u0442\u044c", "callback_data": "ui:advocate"},
                {"text": "\U0001f3e0 \u041c\u0435\u043d\u044e", "callback_data": "ui:main_menu"},
            ],
        ]
    }


def approval_inline_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ ОДОБРИТЬ", "callback_data": "approval:approve"},
                {"text": "❌ ОТКЛОНИТЬ", "callback_data": "approval:reject"},
            ],
            [{"text": "↩️ НА ДОРАБОТКУ", "callback_data": "approval:revise"}],
            [{"text": "🏠 ГЛАВНОЕ МЕНЮ", "callback_data": "ui:main_menu"}],
        ]
    }


def council_mode_keyboard() -> dict:
    """Выбор режима совета адвокатов — Premium."""
    return {
        "inline_keyboard": [
            [{"text": "⚡ БЫСТРЫЙ СОВЕТ  (~30 сек)", "callback_data": "tool:council_quick"}],
            [{"text": "⚖️ СТАНДАРТНЫЙ СОВЕТ  (~90 сек)", "callback_data": "tool:council_standard"}],
            [{"text": "\U0001f3db ПОЛНЫЙ КОНСИЛИУМ  (~3 мин)", "callback_data": "tool:council_full"}],
            [{"text": "← Назад", "callback_data": "ui:main_menu"}],
        ]
    }


def council_result_keyboard() -> dict:
    """Кнопки после завершения совета адвокатов."""
    return {
        "inline_keyboard": [
            [{"text": "\U0001f50d УГЛУБИТЬ АНАЛИЗ", "callback_data": "tool:deepen_analysis"}],
            [
                {"text": "⚖️ Проверить судьёй", "callback_data": "ui:judge_review"},
                {"text": "\U0001f4da Практика", "callback_data": "tool:legal_practice"},
            ],
            [
                {"text": "\U0001f4be Сохранить", "callback_data": "tool:save_to_matter"},
                {"text": "\U0001f3e0 Меню", "callback_data": "ui:main_menu"},
            ],
        ]
    }


class BotConversation:
    def __init__(
        self,
        assistant: LawyerTelegramAssistant,
        store: ClientStore | None = None,
        matter_store: PilotMatterStore | None = None,
    ) -> None:
        self.assistant = assistant
        self.store = store or ClientStore(PROJECT_ROOT / "data" / "bot_client" / "clients.db")
        self.matter_store = matter_store or PilotMatterStore.from_env(PROJECT_ROOT)
        self.pending: dict[str, str] = {}
        self.last_topic: dict[str, str] = {}
        self.compute_mode: dict[str, str] = {}   # chat_id -> COMPUTE_MODE_MAC | COMPUTE_MODE_VPS
        self.pending_doc_meta: dict[str, dict] = {}  # chat_id -> doc metadata awaiting routing choice

    def handle_text(self, chat_id: str, actor_id: str, text: str, message_id: str = "") -> str:
        normalized = text.strip()
        lowered = normalized.lower()
        self.store.ensure_user(chat_id, actor_id)

        if lowered == "/start":
            if not self.store.has_consent(chat_id):
                return (
                    "LegasVex Advocates — внутренний рабочий контур адвокатской практики.\n\n"
                    "Подтвердите доступ к рабочему интерфейсу и обработку материалов дела. "
                    "Не загружайте персональные данные и адвокатскую тайну без полномочий и необходимости."
                )
            return self._welcome(chat_id)

        if lowered in {"/help", "помощь"}:
            return HELP_TEXT

        if lowered in {"/cases", "/дела"}:
            return self._cases(chat_id)

        if lowered in {"/history", "/история"}:
            return self._history(chat_id)

        if lowered in {"/workspace", "/cabinet", "/кабинет", "/профиль"}:
            return self._cabinet(chat_id)

        if lowered == "/risk_scan":
            self.pending[chat_id] = "legal_issue"
            return (
                "Опишите договорное условие или юридическую ситуацию одним сообщением.\n"
                "Укажите: что произошло, какие документы есть, важные даты и желаемый результат."
            )

        if lowered in {"продолжай", "продолжить", "дальше"}:
            topic = self.last_topic.get(chat_id)
            if not topic:
                return "Опишите юридическую ситуацию, которую нужно продолжить разбирать."
            return self._continuation(topic)

        material = self.matter_store.save_text(chat_id, actor_id, normalized, message_id)
        receipt = self._material_receipt(material.matter_id, material.document_id)
        pending = self.pending.pop(chat_id, None)
        if pending == "legal_issue":
            self.last_topic[chat_id] = normalized
            case_id = self.store.create_case(chat_id, normalized)
            self.store.append_message(case_id, "operator", normalized)
            return f"{receipt}\n\n{self._intake_questions(normalized)}"
        if pending == "clarification":
            case = self.store.current_case(chat_id)
            if case:
                self.store.append_message(case["id"], "operator", normalized)
            self.last_topic[chat_id] = f"{self._topic(chat_id)}; уточнение: {normalized}"
            return f"{receipt}\n\n{self._clarification_reply(normalized)}"
        if pending == "document_request":
            case = self.store.current_case(chat_id)
            self.store.add_document(chat_id, case["id"] if case else None, "requested", original_name=normalized)
            return receipt + "\n\n" + (
                f"Запрос на документ зафиксирован: {normalized}\n\n"
                "Пришлите исходные документы и факты. Проект будет подготовлен для проверки адвокатом."
            )

        reply = self.assistant.handle_text(actor_id=actor_id, text=normalized)
        if reply.startswith("Я могу ответить по портфелю"):
            self.last_topic[chat_id] = normalized
            case = self.store.current_case(chat_id)
            if not case:
                case_id = self.store.create_case(chat_id, normalized)
            else:
                case_id = case["id"]
            self.store.append_message(case_id, "operator", normalized)
            return f"{receipt}\n\n{self._intake_questions(normalized)}"
        return f"{receipt}\n\n{reply}"

    def _mode_select_prompt(self) -> str:
        return (
            "\u2696\ufe0f LegasVex Premium\n\n"
            "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0440\u0435\u0436\u0438\u043c \u0440\u0430\u0431\u043e\u0442\u044b:\n\n"
            "\ud83d\udd12 \u041a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0439 \u043a\u043e\u043d\u0442\u0443\u0440\n"
            "\u0412\u0441\u0435 \u0434\u0430\u043d\u043d\u044b\u0435 \u043e\u0441\u0442\u0430\u044e\u0442\u0441\u044f \u0432\u043d\u0443\u0442\u0440\u0438. \u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0443\u0435\u0442\u0441\u044f \u0434\u043b\u044f \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u043e\u0432 \u0441 \u043f\u0435\u0440\u0441\u043e\u043d\u0430\u043b\u044c\u043d\u044b\u043c\u0438 \u0434\u0430\u043d\u043d\u044b\u043c\u0438 "
            "\u0438 \u043c\u0430\u0442\u0435\u0440\u0438\u0430\u043b\u043e\u0432, \u0441\u043e\u0441\u0442\u0430\u0432\u043b\u044f\u044e\u0449\u0438\u0445 \u0430\u0434\u0432\u043e\u043a\u0430\u0442\u0441\u043a\u0443\u044e \u0442\u0430\u0439\u043d\u0443.\n\n"
            "\ud83d\ude80 \u042d\u043a\u0441\u043f\u0435\u0440\u0442\u043d\u044b\u0439 \u0430\u043d\u0430\u043b\u0438\u0437\n"
            "\u0420\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u043d\u044b\u0435 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0434\u043b\u044f \u0441\u0442\u0440\u0430\u0442\u0435\u0433\u0438\u0447\u0435\u0441\u043a\u043e\u0433\u043e \u0430\u043d\u0430\u043b\u0438\u0437\u0430, \u0441\u043e\u0432\u0435\u0442\u0430 \u0430\u0434\u0432\u043e\u043a\u0430\u0442\u043e\u0432 "
            "\u0438 \u0440\u0430\u0431\u043e\u0442\u044b \u0441\u043e \u0441\u043b\u043e\u0436\u043d\u044b\u043c\u0438 \u043f\u0440\u0435\u0446\u0435\u0434\u0435\u043d\u0442\u0430\u043c\u0438."
        )

    def _welcome(self, chat_id: str | None = None) -> str:
        if os.getenv("LEGASVEX_PREMIUM_UI", "true").strip().lower() in {"1", "true", "yes"}:
            if chat_id:
                try:
                    data = get_welcome_data(str(chat_id), self.store)
                    return format_welcome_message(data)
                except Exception:
                    pass
        return WELCOME_TEXT

    def _get_system_status(self) -> str:
        mac_ok = _check_host_reachable(_MAC_MINI_HOST, 11434)
        vps_ok = _check_host_reachable(_VPS_HOST, 22)
        cloud_ok = (
            bool(os.getenv("OPENROUTER_API_KEY") or os.getenv("LEGASVEX_OPENROUTER_API_KEY"))
            and os.getenv("LEGASVEX_ALLOW_CLOUD_LLM", "false").strip().lower() in {"1", "true", "yes"}
        )
        ON = "🟢 ONLINE"
        OFF = "🔴 OFFLINE"
        ON_C = "🟢 ДОСТУПНА"
        OFF_C = "🔴 НЕДОСТУПНА"
        return "\n".join([
            "📊 Статус системы",
            "",
            "🖥 Mac mini: " + (ON if mac_ok else OFF),
            "☁️ VPS: " + (ON if vps_ok else OFF),
            "🤖 Ollama: " + (ON if mac_ok else OFF),
            "🧠 Cloud LLM: " + (ON_C if cloud_ok else OFF_C),
        ])
    def _intake_questions(self, topic: str) -> str:
        ai_analysis = ai_legal_analysis(topic)
        if ai_analysis:
            return (
                f"{ai_analysis}\n\n"
                "Для уточнения добавьте:\n"
                "1. Страну и регион спора\n"
                "2. Стороны и основание обязательства\n"
                "3. Историю обращений, письменный отказ\n"
                "4. Имеющиеся документы\n"
                "5. Желаемый результат и срочность\n\n"
                "Или напишите «Продолжай» для рабочего плана."
            )
        # Fallback — structured template without AI
        return (
            f"Ситуация зафиксирована: {topic}\n\n"
            "Уточните для анализа:\n"
            "1. В какой стране и регионе возник спор?\n"
            "2. Кто стороны и на каком основании возникло обязательство?\n"
            "3. Когда и как вы обращались к другой стороне, есть ли письменный отказ?\n"
            "4. Какие договоры, заявления, расписки или иные документы имеются?\n"
            "5. Какой результат нужен и есть ли срочный срок?\n\n"
            "Добавьте сведения одним сообщением или напишите «Продолжай»."
        )

    def _continuation(self, topic: str) -> str:
        ai_result = ai_continuation(topic, "Продолжи рабочий анализ и сформируй черновой план работы.")
        if ai_result:
            return ai_result
        # Fallback template
        return (
            f"Рабочий план по ситуации: {topic}\n\n"
            "1. Соберите договор, приложения, платёжные документы и переписку.\n"
            "2. Зафиксируйте хронологию обращений и ответов с точными датами.\n"
            "3. Направьте письменное требование с подтверждением вручения.\n"
            "4. Проверьте договорные и законные сроки ответа и обжалования.\n"
            "5. До подачи жалобы или иска — адвокатская проверка материалов и проекта позиции."
        )

    def handle_callback(self, chat_id: str, actor_id: str, data: str) -> tuple[str, dict]:
        self.store.ensure_user(chat_id, actor_id)
        topic = self._topic(chat_id)
        mode = self.compute_mode.get(chat_id)
        if data == "ui:mode_mac_mini":
            self.compute_mode[chat_id] = COMPUTE_MODE_MAC
            return (
                "\U0001f512 \u041a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0439 \u043a\u043e\u043d\u0442\u0443\u0440 \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d.\n\n"
                "\u0412\u0441\u0435 \u043c\u0430\u0442\u0435\u0440\u0438\u0430\u043b\u044b \u043e\u0431\u0440\u0430\u0431\u0430\u0442\u044b\u0432\u0430\u044e\u0442\u0441\u044f \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u043e. \u0414\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 \u043f\u043e\u043a\u0438\u0434\u0430\u044e\u0442 \u0441\u0438\u0441\u0442\u0435\u043c\u0443."
            ), main_inline_keyboard(COMPUTE_MODE_MAC)
        if data == "ui:mode_vps_ai":
            self.compute_mode[chat_id] = COMPUTE_MODE_VPS
            cloud_ok = (
                bool(os.getenv("OPENROUTER_API_KEY") or os.getenv("LEGASVEX_OPENROUTER_API_KEY"))
                and os.getenv("LEGASVEX_ALLOW_CLOUD_LLM", "false").strip().lower() in {"1", "true", "yes"}
            )
            extra = (
                "" if cloud_ok
                else "\n\n\u26a0\ufe0f \u0420\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u043d\u044b\u0439 \u0430\u043d\u0430\u043b\u0438\u0437 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d. \u0411\u0443\u0434\u0435\u0442 \u043f\u0440\u0438\u043c\u0435\u043d\u0451\u043d \u0443\u043f\u0440\u043e\u0449\u0451\u043d\u043d\u044b\u0439 \u0440\u0435\u0436\u0438\u043c."
            )
            return (
                "\U0001f680 \u042d\u043a\u0441\u043f\u0435\u0440\u0442\u043d\u044b\u0439 \u0430\u043d\u0430\u043b\u0438\u0437 \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d." + extra
            ), main_inline_keyboard(COMPUTE_MODE_VPS)
        if data == "ui:change_mode":
            return self._mode_select_prompt(), mode_select_keyboard()
        if data == "ui:system_status":
            return self._get_system_status(), main_inline_keyboard(mode)
        if data == "ui:sensitive_mac":
            meta = self.pending_doc_meta.pop(chat_id, None)
            if not meta:
                return "\u041d\u0435\u0442 \u043e\u0436\u0438\u0434\u0430\u044e\u0449\u0435\u0433\u043e \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430.", main_inline_keyboard(mode)
            reply = self.handle_document(chat_id, actor_id, {**meta, "force_local": True})
            return reply, contextual_inline_keyboard()
        if data == "ui:sensitive_cloud":
            meta = self.pending_doc_meta.pop(chat_id, None)
            if not meta:
                return "\u041d\u0435\u0442 \u043e\u0436\u0438\u0434\u0430\u044e\u0449\u0435\u0433\u043e \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430.", main_inline_keyboard(mode)
            reply = self.handle_document(chat_id, actor_id, {**meta, "force_cloud": True})
            return reply, contextual_inline_keyboard()
        if data == "ui:sensitive_cancel":
            self.pending_doc_meta.pop(chat_id, None)
            return "\u041e\u0442\u043c\u0435\u043d\u0435\u043d\u043e. \u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442 \u043d\u0435 \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d.", main_inline_keyboard(mode)
        if data == "ui:consent_accept":
            self.store.accept_consent(chat_id, actor_id)
            return self._welcome(chat_id), main_inline_keyboard()
        if data == "ui:new_issue":
            self.pending[chat_id] = "legal_issue"
            return (
                "Опишите ситуацию своими словами: что произошло, кто участвует, какие документы и даты есть, "
                "какой результат вам нужен."
            ), main_inline_keyboard()
        if data == "ui:judge_review":
            if not topic:
                return "Сначала опишите ситуацию, которую нужно проверить.", main_inline_keyboard()
            matter_id = self.matter_store.current_matter(chat_id)
            if matter_id:
                analysis = self.matter_store.run_tool(matter_id, "judge_review", actor_id)
                return analysis.content, contextual_inline_keyboard()
            return self._judge_review(topic), contextual_inline_keyboard()
        if data == "ui:clarify":
            self.pending[chat_id] = "clarification"
            return "Добавьте уточнение: даты, документы, действия сторон, суммы и требуемый результат.", contextual_inline_keyboard()
        if data == "ui:document":
            self.pending[chat_id] = "document_request"
            return "Укажите, какой внутренний проект документа нужен и предполагаемого адресата. Внешняя отправка требует проверки адвокатом.", contextual_inline_keyboard()
        if data == "ui:advocate":
            return self._handoff(chat_id, actor_id, topic), approval_inline_keyboard()
        if data == "tool:council":
            # Premium: show mode selection if Premium UI enabled
            if os.getenv("LEGASVEX_PREMIUM_UI", "true").strip().lower() in {"1", "true", "yes"}:
                if not topic:
                    return "Сначала опишите ситуацию.", main_inline_keyboard()
                return (
                    "\U0001f465 Совет адвокатов\n\nВыберите режим анализа:"
                ), council_mode_keyboard()
            if not topic:
                return "Сначала опишите ситуацию.", main_inline_keyboard()
            result = self._run_council(chat_id, actor_id, topic, council_mode="standard")
            return result, council_result_keyboard()
        if data in ("tool:council_quick", "tool:council_standard", "tool:council_full"):
            if not topic:
                return "Сначала опишите ситуацию.", main_inline_keyboard()
            cmode = data.split("_", 1)[1] if "_" in data.split(":", 1)[1] else "standard"
            # council_quick -> "quick", council_standard -> "standard", council_full -> "full"
            cmode = data.replace("tool:council_", "")
            result = self._run_council(chat_id, actor_id, topic, council_mode=cmode)
            return result, council_result_keyboard()
        if data == "tool:deepen_analysis":
            if not topic:
                return "Сначала опишите ситуацию.", main_inline_keyboard()
            # Deep dive: run full council from the last council output
            result = self._run_council(chat_id, actor_id, topic, council_mode="full")
            return result, council_result_keyboard()
        if data == "tool:legal_practice":
            if not topic:
                return "Сначала опишите ситуацию — поиск практики выполняется по вашему делу.", main_inline_keyboard()
            result = search_legal_practice(topic)
            return result, contextual_inline_keyboard()
        if data.startswith("tool:"):
            tool_id = data.split(":", 1)[1]
            if tool_id == "cancel":
                return "Текущий режим отменён. Локально сохранённые материалы не удалены.", main_inline_keyboard()
            matter_id = self.matter_store.current_matter(chat_id)
            if not matter_id:
                return "Сначала сохраните описание ситуации или материал дела.", main_inline_keyboard()
            analysis = self.matter_store.run_tool(matter_id, tool_id, actor_id)
            return analysis.content, contextual_inline_keyboard()
        if data.startswith("approval:"):
            action = data.split(":", 1)[1]
            statuses = {
                "approve": ("approved_internal", "Внутренний черновик одобрен адвокатом."),
                "reject": ("rejected", "Внутренний черновик отклонён адвокатом."),
                "revise": ("revision_requested", "Внутренний черновик направлен на доработку."),
            }
            if action not in statuses:
                return "Действие approval не поддерживается.", contextual_inline_keyboard()
            handoff = self.store.latest_handoff(chat_id)
            if not handoff:
                return "Сначала поставьте рабочий материал в очередь адвокатской проверки.", contextual_inline_keyboard()
            status, message = statuses[action]
            self.store.update_handoff_status(int(handoff["id"]), status)
            matter_id = self.matter_store.current_matter(chat_id)
            if matter_id:
                self.matter_store.record_action(
                    matter_id,
                    "human_approval.updated",
                    actor_id,
                    {
                        "handoff_id": int(handoff["id"]),
                        "status": status,
                        "external_delivery_performed": False,
                    },
                )
            kb = main_inline_keyboard() if status == "rejected" else contextual_inline_keyboard()
            return (
                f"{message}\n\nВнешняя отправка не выполнялась. "
                "Для отправки доверителю требуется отдельное подтверждённое действие адвоката."
            ), kb
        if data == "ui:restart_confirm":
            kb = {"inline_keyboard": [
                [{"text": "\u2705 \u0414\u0410, \u043f\u0435\u0440\u0435\u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c", "callback_data": "ui:restart_do"}],
                [{"text": "\u274c \u041e\u0442\u043c\u0435\u043d\u0430", "callback_data": "ui:main_menu"}],
            ]}
            return "\U0001f504 \u041f\u0435\u0440\u0435\u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u0431\u043e\u0442\u0430?\n\u0412\u0441\u0435 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0435 \u0441\u0435\u0441\u0441\u0438\u0438 \u0431\u0443\u0434\u0443\u0442 \u043f\u0440\u0435\u0440\u0432\u0430\u043d\u044b.", kb
        if data == "ui:restart_do":
            import threading, time as _time
            def _restart():
                _time.sleep(1)
                import os, signal
                # Always send SIGTERM — under systemd this triggers a clean restart.
                # os.execv is intentionally not used: it breaks relative imports
                # when the process was started as a module (python -m ...).
                os.kill(os.getpid(), signal.SIGTERM)
            threading.Thread(target=_restart, daemon=True).start()
            return "\U0001f504 \u0411\u043e\u0442 \u043f\u0435\u0440\u0435\u0437\u0430\u043f\u0443\u0441\u043a\u0430\u0435\u0442\u0441\u044f\u2026 \u0427\u0435\u0440\u0435\u0437 10-15 \u0441\u0435\u043a\u0443\u043d\u0434 \u0431\u0443\u0434\u0435\u0442 \u0433\u043e\u0442\u043e\u0432 \u043a \u0440\u0430\u0431\u043e\u0442\u0435.", main_inline_keyboard(mode)
        if data == "ui:main_menu":
            return "Главное меню.", main_inline_keyboard(mode)
        if data == "ui:risk_scan":
            self.pending[chat_id] = "risk_scan"
            return (
                "Отправьте текст договора или его фрагмент для формальной проверки по правилам.\n\n"
                "⚠️ Анализ выполняется на основе правил — не языковой модели. "
                "Результат является черновиком для адвоката."
            ), contextual_inline_keyboard()
        if data == "ui:cases":
            return self._cases(chat_id), main_inline_keyboard(mode)
        if data == "ui:cabinet":
            return self._cabinet(chat_id), main_inline_keyboard(mode)
        return "\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u0435 \u043d\u0435 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442\u0441\u044f.", main_inline_keyboard(mode)

    def handle_document(self, chat_id: str, actor_id: str, metadata: dict) -> str:
        # Sensitive data routing: on VPS AI mode, offer choice unless already routed
        mode = self.compute_mode.get(chat_id)
        if (
            mode == COMPUTE_MODE_VPS
            and not metadata.get("force_local")
            and not metadata.get("force_cloud")
        ):
            self.pending_doc_meta[chat_id] = metadata
            return "\x00SENSITIVE_ROUTING\x00"
        self.store.ensure_user(chat_id, actor_id)
        case = self.store.current_case(chat_id)
        legacy_document_id = self.store.add_document(
            chat_id,
            case["id"] if case else None,
            metadata.get("extraction_status", "archived"),
            stored_path=metadata.get("stored_path", ""),
            original_name=metadata.get("original_filename", ""),
        )
        if case and metadata.get("extracted_text"):
            self.store.append_message(case["id"], "document", metadata["extracted_text"])
        matter_id = metadata.get("matter_id") or self.matter_store.current_matter(chat_id)
        document_id = metadata.get("document_id")
        if not matter_id or not document_id:
            source_path = Path(metadata.get("stored_path", ""))
            saved = self.matter_store.save_upload(
                chat_id,
                actor_id,
                source_path,
                metadata.get("original_filename", source_path.name),
                metadata.get("mime_type", ""),
                metadata.get("message_id", ""),
            )
            matter_id, document_id = saved.matter_id, saved.document_id
        return (
            "Материал сохранён локально.\n\n"
            f"Дело: {matter_id}\n"
            f"Входящий документ: {document_id}\n"
            f"Legacy record: {legacy_document_id}\n"
            f"Извлечение текста: {metadata.get('extraction_status', 'не выполнено')}.\n\n"
            "Статус: сохранено локально.\n\nВыберите инструмент анализа."
        )

    @staticmethod
    def _material_receipt(matter_id: str, document_id: str) -> str:
        return (
            "Материал сохранён локально.\n\n"
            f"Дело: {matter_id}\n"
            f"Входящий документ: {document_id}\n"
            "Статус: сохранено локально.\n\nВыберите инструмент анализа."
        )

    def _topic(self, chat_id: str) -> str:
        if self.last_topic.get(chat_id):
            return self.last_topic[chat_id]
        case = self.store.current_case(chat_id)
        return case["title"] if case else ""

    def _clarification_reply(self, clarification: str) -> str:
        return (
            f"Уточнение сохранено: {clarification}\n\n"
            "Теперь можно повторить «ИИ СУДЬЯ», добавить документ или направить черновик на адвокатскую проверку."
        )

    def _cases(self, chat_id: str) -> str:
        cases = self.store.list_cases(chat_id)
        if not cases:
            return "У вас пока нет дел. Нажмите «ОПИСАТЬ СИТУАЦИЮ», чтобы создать первое обращение."
        lines = ["МОИ ДЕЛА"]
        for case in cases:
            lines.append(f"#{case['id']} · {case['status']} · {case['title']}")
        return "\n".join(lines)

    def _history(self, chat_id: str) -> str:
        case = self.store.current_case(chat_id)
        if not case:
            return "Активного дела нет."
        messages = self.store.case_messages(case["id"])
        if not messages:
            return f"В деле #{case['id']} пока нет сообщений."
        lines = [f"ИСТОРИЯ ДЕЛА #{case['id']}"]
        for item in messages[-10:]:
            lines.append(f"{item['role']}: {item['content'][:500]}")
        return "\n\n".join(lines)

    def _cabinet(self, chat_id: str) -> str:
        profile = self.store.profile(chat_id)
        return (
            "РАБОЧЕЕ МЕСТО АДВОКАТСКОЙ КОМАНДЫ\n\n"
            f"Дела: {profile['cases']}\n"
            f"Документы: {profile['documents']}\n"
            f"На адвокатской проверке: {profile['handoffs']}"
        )

    def _handoff(self, chat_id: str, actor_id: str, topic: str) -> str:
        case = self.store.current_case(chat_id)
        if not case:
            return "Сначала опишите юридическую ситуацию."
        history = self.store.case_messages(case["id"])
        summary = "\n".join(item["content"] for item in history[-10:]) or topic
        handoff_id = self.store.create_handoff(chat_id, case["id"], summary)
        try:
            result = self.assistant.bridge.submit_intake(
                actor_id=actor_id,
                client_name=f"Доверитель по делу Telegram-{chat_id}",
                summary=summary,
                tags=["advocate-workspace", "trustor-subject", f"local-case-{case['id']}"],
            )
            remote = result.get("intake_id") or result.get("id") or "создано"
            return (
                f"Рабочий материал #{handoff_id} направлен на адвокатскую проверку. Регистрация: {remote}.\n"
                "Добавьте процессуальный срок и недостающие материалы. Внешняя отправка заблокирована до approval."
            )
        except Exception:
            return (
                f"Рабочий материал #{handoff_id} сохранён локально и поставлен в очередь адвокатской проверки.\n"
                "Добавьте процессуальный срок и недостающие материалы. Внешняя отправка заблокирована до approval."
            )


    # Budget presets for council modes
    _COUNCIL_BUDGETS: dict = {"quick": 2, "standard": 4, "full": 8}

    def _run_council(
        self,
        chat_id: str,
        actor_id: str,
        topic: str,
        council_mode: str = "standard",
    ) -> str:
        """Call AgentCouncil + AgentCouncilExecutor inline, return formatted report."""
        import time as _time
        import sys
        from pathlib import Path as _Path
        _v2 = _Path(__file__).resolve().parents[3]
        _orch = str(_v2 / "services" / "orchestrator")
        if _orch not in sys.path:
            sys.path.insert(0, _orch)
        try:
            from orchestrator.agent_council import AgentCouncil
            from orchestrator.agent_execution import AgentCouncilExecutor
            from orchestrator.state_machine import Task, TaskType
        except ImportError as exc:
            return (
                f"⚠️ Совет недоступен: импорт не удался ({exc})\n\n"
                "Убедитесь что оркестратор задеплоен на VPS."
            )

        # Determine task type from topic keywords
        t = topic.lower()
        if any(w in t for w in ("анализ", "legal", "иск", "требование", "ситуация")):
            task_type = TaskType.LEGAL_ANALYSIS
        elif any(w in t for w in ("договор", "контракт", "соглашение")):
            task_type = TaskType.DOCUMENT_DRAFT
        elif any(w in t for w in ("жалоб", "претензи", "complaint")):
            task_type = TaskType.COMPLAINT_PREP
        elif any(w in t for w in ("доказательств", "evidence")):
            task_type = TaskType.EVIDENCE_COLLECT
        else:
            task_type = TaskType.RESEARCH

        budget = self._COUNCIL_BUDGETS.get(council_mode, 4)
        _ts = _time.monotonic()
        try:
            task = Task(type=task_type, description=topic, agent=actor_id)
            council = AgentCouncil(budget_limit=budget)
            plan = council.plan(task)
            executor = AgentCouncilExecutor()
            report = executor.execute(task, plan)
            duration = int(_time.monotonic() - _ts)
            result_text = self._format_council_report(
                report, plan, council_mode=council_mode, duration_sec=duration
            )
            # Replace dry_run technical notice with user-friendly text
            _DRYRUN_MARKER = "Анализ не выполнялся"
            if _DRYRUN_MARKER in result_text:
                result_text = build_dry_run_notice() + "\n\n" + result_text
            # Append transparency footer
            matter_id = self.matter_store.current_matter(chat_id)
            route = "confidential" if self.compute_mode.get(chat_id) == COMPUTE_MODE_MAC else "expert"
            model = "local" if _check_host_reachable(_MAC_MINI_HOST, 11434) else "rule_based"
            footer = build_footer(
                matter_id=matter_id,
                council_used=True,
                council_mode=council_mode,
                route=route,
                model=model,
                duration_sec=duration,
            )
            return result_text + "\n\n" + footer
            # --- legacy path (unreachable) ---
            import re as _re2
            if "\u0410\u043d\u0430\u043b\u0438\u0437 \u043d\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u043b\u0441\u044f" in result_text:
                result_text = (
                    "\u26a0\ufe0f Cloud LLM \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430. Agent Council \u043f\u0435\u0440\u0435\u0432\u0435\u0434\u0451\u043d \u0432 dry_run \u0440\u0435\u0436\u0438\u043c.\n\n"
                    + result_text
                )
            return result_text
        except RuntimeError as exc:
            return (
                f"\u26a0\ufe0f \u0421\u043e\u0432\u0435\u0442 \u0437\u0430\u0432\u0435\u0440\u0448\u0438\u043b\u0441\u044f \u0441 \u043e\u0448\u0438\u0431\u043a\u043e\u0439: {exc}\n\n"
                "\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0447\u0442\u043e Ollama \u0437\u0430\u043f\u0443\u0449\u0435\u043d\u0430 \u0438 \u043c\u043e\u0434\u0435\u043b\u044c \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u0430."
            )
        except Exception as exc:
            return (
                f"⚠️ Внутренняя ошибка совета: {type(exc).__name__}: {exc}\n\n"
                "Подробности — в логах сервиса."
            )

    _ROLE_LABELS = {
        "critic":             "Критик",
        "proceduralist":      "Процессуалист",
        "evidence_analyst":   "Доказательства",
        "strategist":         "Стратег",
        "fact_checker":       "Факты",
        "position_architect": "Правовая позиция",
        "risk_controller":    "Риски",
        "cost_controller":    "Бюджет",
    }

    _COUNCIL_MODE_LABELS_DISPLAY = {
        "quick":    "\u0411\u044b\u0441\u0442\u0440\u044b\u0439 \u00b7 2 \u0440\u043e\u043b\u0438",
        "standard": "\u0421\u0442\u0430\u043d\u0434\u0430\u0440\u0442\u043d\u044b\u0439 \u00b7 4 \u0440\u043e\u043b\u0438",
        "full":     "\u041f\u043e\u043b\u043d\u044b\u0439 \u043a\u043e\u043d\u0441\u0438\u043b\u0438\u0443\u043c \u00b7 8 \u0440\u043e\u043b\u0435\u0439",
    }

    def _format_council_report(
        self,
        report: object,
        plan: object,
        council_mode: str = "standard",
        duration_sec: int | None = None,
    ) -> str:
        import re as _re

        def _clean(text):
            text = _re.sub(r"^\|.*\|[ \t]*$", "", text, flags=_re.MULTILINE)
            text = _re.sub(r"#{1,4}[ \t]*", "", text)
            text = _re.sub(r"\*{1,3}(.*?)\*{1,3}", lambda m: m.group(1), text, flags=_re.DOTALL)
            text = _re.sub(r"^[ \t]*[-\u2013\u2014][ \t]+", "\u2022 ", text, flags=_re.MULTILINE)
            text = _re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()

        DIVIDER = "\u2500" * 24
        mode_label = self._COUNCIL_MODE_LABELS_DISPLAY.get(council_mode, council_mode)
        header_parts = ["\U0001f465 \u0421\u043e\u0432\u0435\u0442 \u0430\u0434\u0432\u043e\u043a\u0430\u0442\u043e\u0432", f"\u2696\ufe0f {mode_label}"]
        if duration_sec is not None:
            header_parts.append(f"{duration_sec} \u0441\u0435\u043a")
        lines = [" \u00b7 ".join(header_parts), ""]

        # Collect results by category
        risks: list[str] = []
        position: str = ""
        disagreements: list[str] = []
        all_results: list[tuple[str, str]] = []  # (label, output)

        for result in report.results:
            if result.role_id == "cost_controller":
                continue
            label = self._ROLE_LABELS.get(result.role_id, result.role_id.replace("_", " ").title())
            if result.status == "dry_run":
                output = "\u0410\u043d\u0430\u043b\u0438\u0437 \u043d\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u043b\u0441\u044f."
            else:
                output = _clean(result.output)
                if len(output) > 900:
                    output = output[:900].rsplit("\n", 1)[0] + "\u2026"
            all_results.append((label, output))
            if result.role_id == "risk_controller":
                risks.append(output)
            elif result.role_id == "position_architect":
                position = output
            elif result.role_id == "critic":
                disagreements.append(f"\u041a\u0440\u0438\u0442\u0438\u043a: {output[:300]}")

        # Premium structured output
        if all_results:
            lines.append(DIVIDER)
            lines.append("\u041a\u0420\u0410\u0422\u041a\u0418\u0419 \u0412\u042b\u0412\u041e\u0414")
            lines.append("")
            # Use position_architect as summary, fallback to first result
            summary = position or (all_results[0][1] if all_results else "")
            lines.append(summary[:600] if summary else "\u2014")
            lines.append("")

        if risks:
            lines.append(DIVIDER)
            lines.append("\u041e\u0421\u041d\u041e\u0412\u041d\u042b\u0415 \u0420\u0418\u0421\u041a\u0418")
            lines.append("")
            for r in risks:
                lines.append(r[:400])
            lines.append("")

        if disagreements:
            lines.append(DIVIDER)
            lines.append("\u0420\u0410\u0417\u041d\u041e\u0413\u041b\u0410\u0421\u0418\u042f \u0420\u041e\u041b\u0415\u0419")
            lines.append("")
            for d in disagreements:
                lines.append(d[:300])
            lines.append("")

        if len(all_results) > 1:
            lines.append(DIVIDER)
            lines.append("\u0414\u0415\u0422\u0410\u041b\u0418 \u041f\u041e \u0420\u041e\u041b\u042f\u041c")
            lines.append("")
            for label, output in all_results:
                if label in ("\u0420\u0438\u0441\u043a\u0438", "\u041f\u0440\u0430\u0432\u043e\u0432\u0430\u044f \u043f\u043e\u0437\u0438\u0446\u0438\u044f"):
                    continue  # already shown above
                lines.append(f"\u25aa {label}")
                lines.append(output[:500])
                lines.append("")

        lines.append(DIVIDER)
        lines.append("\u0427\u0435\u0440\u043d\u043e\u0432\u0438\u043a \u0434\u043b\u044f \u0430\u0434\u0432\u043e\u043a\u0430\u0442\u0430. \u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u043f\u0435\u0440\u0435\u0434 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435\u043c.")
        return "\n".join(lines)
    def _judge_review(self, topic: str) -> str:
        return (
            f"ИИ СУДЬЯ\n\nПредмет: {topic}\n\n"
            "Что суд прежде всего проверит:\n"
            "1. Подсудность, обязательный досудебный порядок и сроки.\n"
            "2. Какие юридически значимые факты подтверждены допустимыми доказательствами.\n"
            "3. Какое право нарушено и соответствует ли ему выбранный способ защиты.\n"
            "4. Какие возражения заявит другая сторона и чем они опровергаются.\n"
            "5. Достаточно ли документов для удовлетворения каждого требования.\n\n"
            "Для предметной проверки приложите документы, даты и сформулируйте требование."
        )


async def main() -> None:
    load_dotenv(ROOT_ENV)
    token = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is missing in v2/.env")
    if os.getenv("HUMAN_APPROVAL_REQUIRED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError("HUMAN_APPROVAL_REQUIRED must be enabled.")
    if os.getenv("DIRECT_CLIENT_DELIVERY", "false").strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("DIRECT_CLIENT_DELIVERY must remain disabled.")

    tenant_scope = os.getenv("LEGASVEX_TENANT_SCOPE", "demo-collegium")
    bridge = LocalAPIBridge(
        crm_base=os.getenv("LEGASVEX_CRM_API_BASE", "http://127.0.0.1:8010"),
        intake_base=os.getenv("LEGASVEX_INTAKE_API_BASE", "http://127.0.0.1:8011"),
        legal_qa_base=os.getenv("LEGASVEX_LEGAL_QA_API_BASE", "http://127.0.0.1:8015"),
        tenant_scope=tenant_scope,
    )
    assistant = LawyerTelegramAssistant(bridge)
    matter_store = PilotMatterStore.from_env(PROJECT_ROOT)
    conversation = BotConversation(
        assistant,
        ClientStore(PROJECT_ROOT / "data" / "bot_client" / "clients.db"),
        matter_store,
    )
    access_policy = BotAccessPolicy.from_env()
    api = TelegramBotAPI(token)

    await asyncio.to_thread(api.call, "deleteWebhook", {"drop_pending_updates": "true"})
    me = await asyncio.to_thread(api.call, "getMe")
    print(f"LegasVex Bot API assistant ready: @{me.get('username', 'unknown')}", flush=True)

    offset = 0
    while True:
        try:
            updates = await asyncio.to_thread(
                api.call,
                "getUpdates",
                {"offset": offset, "timeout": 25, "allowed_updates": ["message", "callback_query"]},
                35,
            )
            for update in updates:
                offset = max(offset, int(update["update_id"]) + 1)
                callback = update.get("callback_query") or {}
                if callback:
                    callback_message = callback.get("message") or {}
                    callback_chat = callback_message.get("chat") or {}
                    callback_sender = callback.get("from") or {}
                    chat_id = str(callback_chat.get("id", ""))
                    actor_id = str(callback_sender.get("id", "telegram-user"))
                    if not access_policy.authorize(actor_id, chat_id):
                        await asyncio.to_thread(
                            api.call,
                            "answerCallbackQuery",
                            {"callback_query_id": callback.get("id", ""), "text": ACCESS_DENIED_TEXT},
                        )
                        continue
                    cb_data = callback.get("data", "")
                    _is_council_exec = cb_data in (
                        "tool:council_quick", "tool:council_standard",
                        "tool:council_full", "tool:deepen_analysis",
                    )
                    # Classic "tool:council" in non-Premium mode also runs council directly
                    _is_council_classic = (
                        cb_data == "tool:council"
                        and os.getenv("LEGASVEX_PREMIUM_UI", "true").strip().lower()
                        not in {"1", "true", "yes"}
                    )
                    if _is_council_exec or _is_council_classic:
                        _cmode = "standard"
                        if cb_data == "tool:council_quick":
                            _cmode = "quick"
                        elif cb_data in ("tool:council_full", "tool:deepen_analysis"):
                            _cmode = "full"
                        _mode_short = {"quick": "⚡ Быстрый", "standard": "⚖️ Стандартный", "full": "🏛 Полный консилиум"}
                        await asyncio.to_thread(
                            api.call, "answerCallbackQuery",
                            {"callback_query_id": callback.get("id", ""),
                             "text": f"\U0001f465 {_mode_short.get(_cmode, 'Анализ')} — начинается…"},
                        )
                        topic = conversation._topic(chat_id)
                        if not topic:
                            await asyncio.to_thread(
                                api.call, "sendMessage",
                                {"chat_id": chat_id, "text": "Сначала опишите ситуацию."},
                            )
                            continue
                        import time as _time
                        _start_ts = _time.monotonic()
                        _expected_sec = {"quick": 35, "standard": 90, "full": 180}[_cmode]
                        _mode_line_map = {"quick": "⚡ Быстрый совет", "standard": "⚖️ Стандартный совет", "full": "\U0001f3db Полный консилиум"}

                        def _countdown_text(elapsed, _cmode=_cmode, _exp=_expected_sec):
                            m, s = divmod(int(elapsed), 60)
                            bar_total = 12
                            filled = min(bar_total, int(elapsed / _exp * bar_total))
                            bar = "█" * filled + "░" * (bar_total - filled)
                            return "\n".join([
                                "\U0001f465 Совет адвокатов",
                                "",
                                _mode_line_map.get(_cmode, "Анализ"),
                                "Анализирует дело…",
                                "",
                                "[" + bar + "]",
                                str(m) + ":" + str(s).zfill(2),
                            ])

                        anim_msg = await asyncio.to_thread(
                            api.call, "sendMessage",
                            {"chat_id": chat_id, "text": _countdown_text(0)},
                        )
                        anim_msg_id = str(anim_msg.get("message_id", ""))
                        council_task = asyncio.ensure_future(
                            asyncio.to_thread(
                                conversation._run_council, chat_id, actor_id, topic, _cmode
                            )
                        )
                        _last_edit = 0.0
                        while not council_task.done():
                            elapsed = _time.monotonic() - _start_ts
                            if elapsed - _last_edit >= 5.0:
                                try:
                                    await asyncio.to_thread(
                                        api.call, "editMessageText",
                                        {"chat_id": chat_id, "message_id": anim_msg_id,
                                         "text": _countdown_text(elapsed)},
                                    )
                                    _last_edit = elapsed
                                except Exception:
                                    pass
                            await asyncio.sleep(1.0)
                        reply = await council_task
                        chunks = split_message(reply)
                        for i, chunk in enumerate(chunks):
                            if i == 0:
                                try:
                                    await asyncio.to_thread(
                                        api.call, "editMessageText",
                                        {"chat_id": chat_id, "message_id": anim_msg_id,
                                         "text": chunk,
                                         "reply_markup": council_result_keyboard()},
                                    )
                                except Exception:
                                    await asyncio.to_thread(
                                        api.call, "sendMessage",
                                        {"chat_id": chat_id, "text": chunk,
                                         "reply_markup": council_result_keyboard()},
                                    )
                            else:
                                await asyncio.to_thread(
                                    api.call, "sendMessage",
                                    {"chat_id": chat_id, "text": chunk,
                                     "reply_markup": council_result_keyboard()},
                                )
                        continue

                    if cb_data == "tool:council" and os.getenv(
                        "LEGASVEX_PREMIUM_UI", "true"
                    ).strip().lower() in {"1", "true", "yes"}:
                        # Premium: show mode selection keyboard via handle_callback
                        reply, keyboard = await asyncio.to_thread(
                            conversation.handle_callback, chat_id, actor_id, cb_data
                        )
                        await asyncio.to_thread(
                            api.call, "answerCallbackQuery",
                            {"callback_query_id": callback.get("id", "")},
                        )
                        await asyncio.to_thread(
                            api.call, "sendMessage",
                            {"chat_id": chat_id, "text": reply, "reply_markup": keyboard},
                        )
                        continue

                    if cb_data == "tool:council":
                        # Classic (non-Premium) path — Answer immediately — council can take 1-3 min with Ollama
                        await asyncio.to_thread(
                            api.call,
                            "answerCallbackQuery",
                            {"callback_query_id": callback.get("id", ""),
                             "text": "👥 Совет адвокатов начинает анализ…"},
                        )
                        topic = conversation._topic(chat_id)
                        if not topic:
                            await asyncio.to_thread(
                                api.call, "sendMessage",
                                {"chat_id": chat_id, "text": "Сначала опишите ситуацию."},
                            )
                            continue
                        # Send countdown waiting message
                        import time as _time
                        _start_ts = _time.monotonic()

                        def _countdown_text(elapsed):
                            m, s = divmod(int(elapsed), 60)
                            bar_total = 12
                            filled = min(bar_total, int(elapsed / 90 * bar_total))
                            bar = "\u2588" * filled + "\u2591" * (bar_total - filled)
                            return "\n".join([
                                "\U0001f465 \u0421\u043e\u0432\u0435\u0442 \u0430\u0434\u0432\u043e\u043a\u0430\u0442\u043e\u0432",
                                "",
                                "\u0410\u043d\u0430\u043b\u0438\u0437\u0438\u0440\u0443\u0435\u0442 \u0434\u0435\u043b\u043e\u2026",
                                "",
                                "[" + bar + "]",
                                str(m) + ":" + str(s).zfill(2),
                            ])

                        anim_msg = await asyncio.to_thread(
                            api.call, "sendMessage",
                            {"chat_id": chat_id, "text": _countdown_text(0)},
                        )
                        anim_msg_id = str(anim_msg.get("message_id", ""))
                        council_task = asyncio.ensure_future(
                            asyncio.to_thread(conversation._run_council, chat_id, actor_id, topic)
                        )
                        _last_edit = 0.0
                        while not council_task.done():
                            elapsed = _time.monotonic() - _start_ts
                            if elapsed - _last_edit >= 5.0:
                                try:
                                    await asyncio.to_thread(
                                        api.call, "editMessageText",
                                        {"chat_id": chat_id, "message_id": anim_msg_id,
                                         "text": _countdown_text(elapsed)},
                                    )
                                    _last_edit = elapsed
                                except Exception:
                                    pass
                            await asyncio.sleep(1.0)
                        reply = await council_task
                        # Replace animation message with first chunk of result
                        chunks = split_message(reply)
                        for i, chunk in enumerate(chunks):
                            if i == 0:
                                try:
                                    await asyncio.to_thread(
                                        api.call, "editMessageText",
                                        {"chat_id": chat_id, "message_id": anim_msg_id,
                                         "text": chunk,
                                         "reply_markup": contextual_inline_keyboard()},
                                    )
                                except Exception:
                                    await asyncio.to_thread(
                                        api.call, "sendMessage",
                                        {"chat_id": chat_id, "text": chunk,
                                         "reply_markup": contextual_inline_keyboard()},
                                    )
                            else:
                                await asyncio.to_thread(
                                    api.call, "sendMessage",
                                    {"chat_id": chat_id, "text": chunk,
                                     "reply_markup": contextual_inline_keyboard()},
                                )
                        continue
                    reply, keyboard = await asyncio.to_thread(
                        conversation.handle_callback, chat_id, actor_id, cb_data
                    )
                    await asyncio.to_thread(
                        api.call,
                        "answerCallbackQuery",
                        {"callback_query_id": callback.get("id", "")},
                    )
                    await asyncio.to_thread(
                        api.call,
                        "sendMessage",
                        {"chat_id": chat_id, "text": reply, "reply_markup": keyboard},
                    )
                    continue
                message = update.get("message") or {}
                text = (message.get("text") or "").strip()
                chat = message.get("chat") or {}
                sender = message.get("from") or {}
                chat_id = str(chat.get("id", ""))
                actor_id = str(sender.get("id", "telegram-user"))
                message_id = str(message.get("message_id", ""))
                if not access_policy.authorize(actor_id, chat_id):
                    append_message_log(
                        PROJECT_ROOT,
                        {
                            "tenant_scope": tenant_scope,
                            "transport": "bot_api",
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "direction": "access_denied",
                            "actor_id": actor_id,
                            "role": access_policy.role_for(actor_id),
                            "text_preview": "",
                        },
                    )
                    await asyncio.to_thread(
                        api.call,
                        "sendMessage",
                        {
                            "chat_id": chat_id,
                            "text": ACCESS_DENIED_TEXT,
                            "reply_to_message_id": message_id,
                        },
                    )
                    continue
                document = message.get("document") or {}
                photos = message.get("photo") or []
                if document or photos:
                    attachment = document or photos[-1]
                    original_name = document.get("file_name") or f"telegram_photo_{message_id}.jpg"
                    mime_type = document.get("mime_type") or "image/jpeg"
                    target = build_archive_path(PROJECT_ROOT, original_name, chat_id, message_id, datetime.now())
                    await asyncio.to_thread(api.download_file, attachment["file_id"], target)
                    saved = matter_store.save_upload(
                        chat_id, actor_id, target, original_name, mime_type, message_id
                    )
                    stored_path = Path(saved.stored_path)
                    extracted = extract_document_text(stored_path, mime_type=mime_type)
                    metadata = {
                        "tenant_scope": tenant_scope,
                        "transport": "bot_api",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "matter_id": saved.matter_id,
                        "document_id": saved.document_id,
                        "original_filename": original_name,
                        "stored_path": str(stored_path),
                        "mime_type": mime_type,
                        "caption": message.get("caption") or "",
                        "extraction_status": extracted.status,
                        "extractor": extracted.extractor,
                        "extracted_text": extracted.text,
                    }
                    target.unlink(missing_ok=True)
                    reply = await asyncio.to_thread(
                        conversation.handle_document, chat_id, actor_id, metadata
                    )
                    if reply == "\x00SENSITIVE_ROUTING\x00":
                        _sens_text = (
                            "\U0001f512 \u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442 \u0441\u043e\u0434\u0435\u0440\u0436\u0438\u0442 \u0447\u0443\u0432\u0441\u0442\u0432\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435.\n\n"
                            "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0441\u043f\u043e\u0441\u043e\u0431 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438:\n\n"
                            "\U0001f5a5 \u041e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u0442\u044c \u043d\u0430 Mac mini \u2014 \u043a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u043e, Zero Leakage\n"
                            "\u2601\ufe0f \u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0432 Cloud LLM \u2014 \u0431\u043e\u043b\u0435\u0435 \u043c\u043e\u0449\u043d\u044b\u0439 \u0430\u043d\u0430\u043b\u0438\u0437"
                        )
                        await asyncio.to_thread(
                            api.call, "sendMessage",
                            {"chat_id": chat_id, "text": _sens_text,
                             "reply_to_message_id": message_id,
                             "reply_markup": sensitive_data_keyboard()},
                        )
                    else:
                        await asyncio.to_thread(
                            api.call,
                            "sendMessage",
                            {
                                "chat_id": chat_id,
                                "text": reply,
                                "reply_to_message_id": message_id,
                                "reply_markup": contextual_inline_keyboard(),
                            },
                        )
                    continue
                if not text:
                    continue
                append_message_log(
                    PROJECT_ROOT,
                    {
                        "tenant_scope": tenant_scope,
                        "transport": "bot_api",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "direction": "incoming",
                        "actor_id": actor_id,
                        "text_preview": text_preview(text),
                    },
                )
                try:
                    reply = await asyncio.to_thread(
                        conversation.handle_text,
                        chat_id=chat_id, actor_id=actor_id, text=text, message_id=message_id
                    )
                except Exception as exc:
                    print(f"Bot API assistant handling error: {exc}", flush=True)
                    reply = "Сервис временно недоступен. Повторите запрос позже."
                chunks = split_message(reply)
                _chat_mode = conversation.compute_mode.get(chat_id)
                if text.lower() == "/start" and not conversation.store.has_consent(chat_id):
                    keyboard = consent_inline_keyboard()
                elif text.lower() == "/start" and chat_id not in conversation.compute_mode:
                    keyboard = mode_select_keyboard()
                elif text.lower() in {"/start", "/help", "/cases", "/дела", "/cabinet", "/кабинет"}:
                    keyboard = main_inline_keyboard(_chat_mode)
                else:
                    keyboard = contextual_inline_keyboard()
                for index, chunk in enumerate(chunks):
                    sent = await asyncio.to_thread(
                        api.call,
                        "sendMessage",
                        {
                            "chat_id": chat_id,
                            "text": chunk,
                            "reply_to_message_id": message_id,
                            "reply_markup": keyboard if index == len(chunks) - 1 else None,
                        },
                    )
                    append_message_log(
                        PROJECT_ROOT,
                        {
                            "tenant_scope": tenant_scope,
                            "transport": "bot_api",
                            "chat_id": chat_id,
                            "message_id": str(sent.get("message_id", "")),
                            "direction": "assistant_reply",
                            "actor_id": "assistant",
                            "reply_to_message_id": message_id,
                                        "text_preview": text_preview(chunk),
                        },
                    )
        except (error.URLError, TimeoutError, RuntimeError, OSError, ssl.SSLError) as exc:
            print(f"Bot API polling error: {type(exc).__name__}: {exc}; retrying.", flush=True)
            await asyncio.sleep(5)
        except Exception as exc:
            print(f"Bot API unexpected error: {type(exc).__name__}: {exc}; retrying.", flush=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
