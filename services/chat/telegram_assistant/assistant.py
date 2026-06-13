from __future__ import annotations

from .api_bridge import LocalAPIBridge
from .command_parser import parse_command
from .formatter import (
    format_dashboard,
    format_help,
    format_intake_result,
    format_contract_risk_scan,
    format_deadline_answer,
    format_demo_script,
    format_document_upload_result,
    format_matter,
    format_portfolio,
    format_risk_answer,
)


class LawyerTelegramAssistant:
    def __init__(self, bridge: LocalAPIBridge) -> None:
        self.bridge = bridge

    def handle_text(self, actor_id: str, text: str) -> str:
        command = parse_command(text)

        if command.name in {"empty", "/start", "/help"}:
            return format_help()
        if command.name == "/demo":
            return format_demo_script()
        if command.name == "/seed":
            counts = self.bridge.seed_demo()
            return (
                "Demo loaded\n"
                f"Clients: {counts['clients']}\n"
                f"Matters: {counts['matters']}\n"
                f"Assignments: {counts['assignments']}\n"
                f"Deadlines: {counts['deadlines']}"
            )
        if command.name == "/dashboard":
            return format_dashboard(self.bridge.dashboard())
        if command.name == "/portfolio":
            return format_portfolio(self.bridge.portfolio())
        if command.name == "/matter":
            if not command.argument:
                return "Usage: /matter <matter_id>"
            return format_matter(self.bridge.matter(command.argument))
        if command.name == "/intake":
            return self._handle_intake(actor_id, command.argument)
        if command.name == "/risk_scan":
            return self._handle_contract_risk_scan(actor_id, command.argument)
        if command.name.startswith("/"):
            return "Unknown command. Use /help."
        return self._handle_question(actor_id, command.argument or text.strip())

    def _handle_question(self, actor_id: str, text: str) -> str:
        normalized = text.strip()
        lowered = normalized.lower()
        if not normalized:
            return format_help()

        matter_id = self._extract_matter_id(normalized)
        if matter_id and self._looks_like_matter_question(lowered):
            return format_matter(self.bridge.matter(matter_id))

        if self._looks_like_demo_question(lowered):
            return format_demo_script()

        if self._looks_like_risk_scan(lowered):
            return self._handle_natural_risk_scan(actor_id, normalized, matter_id)

        if self._looks_like_risk_question(lowered):
            return format_risk_answer(self.bridge.dashboard())

        if self._looks_like_deadline_question(lowered):
            return format_deadline_answer(self.bridge.dashboard())

        if self._looks_like_portfolio_question(lowered):
            return format_portfolio(self.bridge.portfolio())

        if self._looks_like_dashboard_question(lowered):
            return format_dashboard(self.bridge.dashboard())

        if self._looks_like_intake_request(lowered):
            return self._handle_intake(actor_id, self._strip_intake_prefix(normalized))

        return (
            "Я могу ответить по портфелю, рискам, срокам и делам, либо проверить договор.\n"
            "Пример: «Проверь договор по делу matter-123: ...»"
        )

    def handle_document(self, actor_id: str, metadata: dict, caption: str = "") -> str:
        caption_text = caption or metadata.get("caption", "")
        matter_id = self._extract_matter_id(caption_text) or metadata.get("suggested_matter_id")
        if not matter_id:
            matter_id = self._first_matter_id()
        if not matter_id:
            return (
                "Документ принят в archive, но дело не определено.\n"
                "Пришлите подпись в формате: договор по делу matter-..."
            )

        review_type = "contract"
        review = self.bridge.document_review(
            actor_id=actor_id,
            matter_id=matter_id,
            metadata={**metadata, "caption": caption_text},
            review_type=review_type,
        )
        return format_document_upload_result(
            {
                "metadata": metadata,
                "matter_id": matter_id,
                "review_type": review_type,
                "review": review,
                "status": "создана задача на проверку адвокатом",
            }
        )

    def _handle_intake(self, actor_id: str, argument: str) -> str:
        if "|" in argument:
            client_name, summary = [part.strip() for part in argument.split("|", maxsplit=1)]
        else:
            client_name = "Telegram Intake"
            summary = argument.strip()
        if not summary:
            return "Usage: /intake <client> | <summary>"
        result = self.bridge.submit_intake(
            actor_id=actor_id,
            client_name=client_name,
            summary=summary,
            tags=self._derive_tags(summary),
        )
        return format_intake_result(result)

    def _derive_tags(self, summary: str) -> list[str]:
        lowered = summary.lower()
        tags = []
        if "court" in lowered or "claim" in lowered or "complaint" in lowered:
            tags.append("court")
        if "urgent" in lowered or "deadline" in lowered:
            tags.append("urgent")
        return tags

    def _handle_contract_risk_scan(self, actor_id: str, argument: str) -> str:
        if "|" not in argument:
            return "Usage: /risk_scan <matter_id> | <contract text>"
        matter_id, text = [part.strip() for part in argument.split("|", maxsplit=1)]
        if not matter_id or not text:
            return "Usage: /risk_scan <matter_id> | <contract text>"
        result = self.bridge.contract_risk_scan(
            actor_id=actor_id,
            matter_id=matter_id,
            text=text,
            source_document_id="telegram",
        )
        return format_contract_risk_scan(result)

    def _handle_natural_risk_scan(self, actor_id: str, text: str, matter_id: str | None) -> str:
        target_matter_id = matter_id or self._first_matter_id()
        if not target_matter_id:
            return "Не нашел активное дело. Сначала загрузите демо или создайте обращение."
        contract_text = self._strip_risk_scan_prefix(text)
        if len(contract_text) < 20:
            return "Пришлите текст условия договора после слов «проверь договор»."
        result = self.bridge.contract_risk_scan(
            actor_id=actor_id,
            matter_id=target_matter_id,
            text=contract_text,
            source_document_id="telegram-qa",
        )
        return format_contract_risk_scan(result)

    def _first_matter_id(self) -> str | None:
        portfolio = self.bridge.portfolio()
        if not portfolio:
            return None
        return str(portfolio[0].get("matter_id") or "") or None

    def _extract_matter_id(self, text: str) -> str | None:
        for token in text.replace(":", " ").replace("|", " ").split():
            cleaned = token.strip(",.;()[]")
            if cleaned.startswith("matter-"):
                return cleaned
        return None

    def _looks_like_matter_question(self, lowered: str) -> bool:
        return any(word in lowered for word in ("дел", "matter", "case"))

    def _looks_like_risk_scan(self, lowered: str) -> bool:
        return (
            ("договор" in lowered or "contract" in lowered or "услов" in lowered)
            and any(word in lowered for word in ("проверь", "проверить", "scan", "риск", "анализ"))
        )

    def _looks_like_risk_question(self, lowered: str) -> bool:
        return any(word in lowered for word in ("риск", "risk", "опасн"))

    def _looks_like_deadline_question(self, lowered: str) -> bool:
        return any(word in lowered for word in ("срок", "deadline", "дедлайн", "просроч"))

    def _looks_like_portfolio_question(self, lowered: str) -> bool:
        return any(word in lowered for word in ("портфель", "список дел", "активные дела", "portfolio"))

    def _looks_like_dashboard_question(self, lowered: str) -> bool:
        return any(word in lowered for word in ("сводк", "dashboard", "обзор", "статус коллегии"))

    def _looks_like_demo_question(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in ("покажи демо", "что ты умеешь", "как проверить договор", "как загрузить документ"))

    def _looks_like_intake_request(self, lowered: str) -> bool:
        return any(word in lowered for word in ("создай обращение", "новое обращение", "intake", "зарегистрируй"))

    def _strip_intake_prefix(self, text: str) -> str:
        prefixes = ("создай обращение:", "создай обращение", "новое обращение:", "новое обращение", "зарегистрируй:")
        lowered = text.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return text[len(prefix):].strip()
        return text

    def _strip_risk_scan_prefix(self, text: str) -> str:
        lowered = text.lower()
        markers = ("проверь договор", "проверить договор", "анализ договора", "scan contract", "contract risk")
        for marker in markers:
            idx = lowered.find(marker)
            if idx >= 0:
                return text[idx + len(marker):].lstrip(" :|-")
        matter_id = self._extract_matter_id(text)
        if matter_id:
            return text.replace(matter_id, "", 1).strip(" :|-")
        return text
