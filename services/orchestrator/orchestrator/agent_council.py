from __future__ import annotations

from dataclasses import asdict, dataclass

from .state_machine import Task, TaskType


@dataclass(frozen=True)
class CouncilRole:
    role_id: str
    label: str
    purpose: str
    estimated_units: int


@dataclass(frozen=True)
class CouncilPlan:
    roles: list[CouncilRole]
    checks: list[str]
    requires_human_review: bool
    estimated_units: int
    budget_limit: int
    omitted_roles: list[str]

    def as_dict(self) -> dict:
        return {
            "roles": [asdict(role) for role in self.roles],
            "checks": self.checks,
            "requires_human_review": self.requires_human_review,
            "estimated_units": self.estimated_units,
            "budget_limit": self.budget_limit,
            "omitted_roles": self.omitted_roles,
        }


ROLE_REGISTRY = {
    "critic": CouncilRole("critic", "Критик", "Ищет слабые места и логические ошибки.", 1),
    "proceduralist": CouncilRole(
        "proceduralist", "Процессуалист", "Проверяет сроки, подсудность и процессуальные требования.", 2
    ),
    "evidence_analyst": CouncilRole(
        "evidence_analyst", "Аналитик доказательств", "Связывает утверждения с фактами и источниками.", 2
    ),
    "strategist": CouncilRole("strategist", "Стратег", "Формирует варианты правовой стратегии.", 2),
    "fact_checker": CouncilRole("fact_checker", "Факт-чекер", "Проверяет данные и наличие источников.", 1),
    "position_architect": CouncilRole(
        "position_architect", "Архитектор правовой позиции", "Строит структуру аргументов и защиты.", 2
    ),
    "risk_controller": CouncilRole("risk_controller", "Риск-контролёр", "Оценивает юридические риски.", 1),
    "cost_controller": CouncilRole(
        "cost_controller", "Финансовый контролёр", "Контролирует бюджет агентной проверки.", 0
    ),
}

BASE_CHECKS = ["source_required", "logic_review", "human_review_before_legal_effect"]

ROLE_RULES: dict[TaskType, list[str]] = {
    TaskType.LEGAL_ANALYSIS: [
        "evidence_analyst",
        "risk_controller",
        "critic",
        "fact_checker",
    ],
    TaskType.DOCUMENT_DRAFT: [
        "position_architect",
        "critic",
        "risk_controller",
    ],
    TaskType.DOCUMENT_FINAL: [
        "fact_checker",
        "proceduralist",
        "critic",
    ],
    TaskType.COMPLAINT_PREP: [
        "proceduralist",
        "evidence_analyst",
    ],
    TaskType.COMPLAINT_SEND: [
        "proceduralist",
        "fact_checker",
        "risk_controller",
    ],
    TaskType.EVIDENCE_COLLECT: [
        "evidence_analyst",
        "fact_checker",
        "critic",
    ],
    TaskType.RESEARCH: [
        "fact_checker",
        "critic",
        "risk_controller",
    ],
}


class AgentCouncil:
    # Premium council mode budget presets
    BUDGET_QUICK: int = 2     # ~30 sec — critic + risk_controller
    BUDGET_STANDARD: int = 4  # ~90 sec — default 4 roles
    BUDGET_FULL: int = 8      # ~3 min  — all 8 roles

    def __init__(self, budget_limit: int = 4) -> None:
        self.budget_limit = max(1, budget_limit)

    def plan(self, task: Task) -> CouncilPlan:
        requested = ROLE_RULES.get(task.type, ["critic", "risk_controller"])
        selected: list[CouncilRole] = [ROLE_REGISTRY["cost_controller"]]
        omitted: list[str] = []
        spent = 0

        for role_id in requested:
            role = ROLE_REGISTRY[role_id]
            if spent + role.estimated_units > self.budget_limit:
                omitted.append(role_id)
                continue
            selected.append(role)
            spent += role.estimated_units

        checks = list(BASE_CHECKS)
        if task.type in {TaskType.LEGAL_ANALYSIS, TaskType.COMPLAINT_PREP, TaskType.COMPLAINT_SEND}:
            checks.extend(["applicable_law_review", "procedural_deadline_review"])
        if omitted:
            checks.append("budget_limited_review")

        human_review_types = {
            TaskType.LEGAL_ANALYSIS,
            TaskType.DOCUMENT_FINAL,
            TaskType.COMPLAINT_PREP,
            TaskType.COMPLAINT_SEND,
        }
        return CouncilPlan(
            roles=selected,
            checks=checks,
            requires_human_review=(task.type in human_review_types),
            estimated_units=spent,
            budget_limit=self.budget_limit,
            omitted_roles=omitted,
        )
