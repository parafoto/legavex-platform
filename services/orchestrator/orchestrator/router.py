from .state_machine import Task, TaskType


class AgentRouter:
    AGENT_MAP = {
        TaskType.LEGAL_ANALYSIS: "legal_ru",
        TaskType.DOCUMENT_DRAFT: "document",
        TaskType.DOCUMENT_FINAL: "legal_ru",
        TaskType.COMPLAINT_PREP: "legal_ru",
        TaskType.COMPLAINT_SEND: "fssp",
        TaskType.EVIDENCE_COLLECT: "evidence",
        TaskType.CASE_CREATE: "crm",
        TaskType.CASE_UPDATE: "crm",
        TaskType.CLIENT_INTAKE: "crm",
        TaskType.CODE_GENERATE: "codex",
        TaskType.CODE_REFACTOR: "claude",
        TaskType.ADMIN: "ollama",
        TaskType.RESEARCH: "deepseek",
    }

    COUNTRY_AGENTS = {
        "ru": "legal_ru",
        "ua": "legal_ua",
        "de": "legal_de",
    }

    def route(self, task: Task) -> str:
        if task.type in (
            TaskType.LEGAL_ANALYSIS,
            TaskType.DOCUMENT_DRAFT,
            TaskType.COMPLAINT_PREP,
            TaskType.COMPLAINT_SEND,
        ):
            return self.COUNTRY_AGENTS.get(task.country, "legal_ru")
        if "scooter" in task.tags or "carsharing" in task.tags:
            return "scooter"
        return self.AGENT_MAP.get(task.type, "ollama")

