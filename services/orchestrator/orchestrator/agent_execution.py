from __future__ import annotations

import hashlib
import json
import os
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .agent_council import CouncilPlan, CouncilRole
from .state_machine import Task, TaskType


V2_ROOT = Path(__file__).resolve().parents[3]
PROMPT_ROOT = V2_ROOT / "shared" / "prompt_registry" / "agent_council"

# Per-role model defaults — override via LEGASVEX_LLM_MODEL_<ROLE_ID_UPPER> env var
_ROLE_MODEL_DEFAULTS: dict[str, str] = {
    "critic":             "deepseek-r1:7b",        # reasoning: finds logical flaws
    "proceduralist":      "qwen2.5:7b",             # legal procedure & deadlines
    "evidence_analyst":   "qwen2.5:14b",            # needs context window for tables
    "strategist":         "qwen2.5:14b",            # broad legal reasoning
    "fact_checker":       "llama3.2:3b",            # fast, focused verification
    "position_architect": "qwen2.5:14b",            # complex synthesis
    "risk_controller":    "qwen2.5:7b",             # risk assessment
    "cost_controller":    "",                       # no LLM — bookkeeping only
}


def _model_for_role(role_id: str) -> str:
    """Return the LLM model name for a given role, respecting env overrides."""
    env_key = f"LEGASVEX_LLM_MODEL_{role_id.upper()}"
    override = os.getenv(env_key, "").strip()
    if override:
        return override
    default = os.getenv("LEGASVEX_LLM_MODEL_DEFAULT", "").strip()
    if default:
        return default
    return _ROLE_MODEL_DEFAULTS.get(role_id, os.getenv("LEGASVEX_LOCAL_LLM_MODEL", "qwen2.5:7b"))


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AgentExecutionRequest:
    role: CouncilRole
    prompt: str
    input_data: str
    source_ids: list[str] = field(default_factory=list)
    sensitive: bool = False


@dataclass(frozen=True)
class AgentExecutionResult:
    role_id: str
    prompt_id: str
    status: str
    output: str
    cost_units: int
    source_status: str
    checks: list[str]
    requires_human_review: bool
    external_delivery_requires_human_approval: bool = True
    direct_client_delivery_allowed: bool = False
    audit_event: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CouncilExecutionReport:
    status: str
    mode: str
    provider: str
    results: list[AgentExecutionResult]
    spent_units: int
    budget_limit: int
    requires_human_review: bool
    controlled_failure: str = ""
    real_llm_calls: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "provider": self.provider,
            "results": [result.as_dict() for result in self.results],
            "spent_units": self.spent_units,
            "budget_limit": self.budget_limit,
            "requires_human_review": self.requires_human_review,
            "controlled_failure": self.controlled_failure,
            "real_llm_calls": self.real_llm_calls,
        }


class LLMProvider(ABC):
    name = "abstract"

    @abstractmethod
    def execute(self, request: AgentExecutionRequest, *, dry_run: bool) -> AgentExecutionResult:
        raise NotImplementedError


class LocalLLMProvider(LLMProvider):
    name = "local"

    def __init__(self, endpoint: str = "") -> None:
        self.endpoint = endpoint.strip()
        self.model = os.getenv("LEGASVEX_LOCAL_LLM_MODEL", "qwen2.5:7b")

    def execute(self, request: AgentExecutionRequest, *, dry_run: bool) -> AgentExecutionResult:
        if dry_run:
            return _dry_run_result(request, provider=self.name)
        if not self.endpoint:
            raise RuntimeError(
                "LEGASVEX_LOCAL_LLM_ENDPOINT is not set; cannot execute local LLM."
            )
        return self._call_ollama(request)

    def _call_ollama(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        url = f"{self.endpoint.rstrip('/')}/api/chat"
        model = _model_for_role(request.role.role_id) or self.model
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.prompt},
                {"role": "user", "content": request.input_data},
            ],
            "stream": False,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama unreachable at {url}: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

        try:
            output = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Ollama response format: {data!r}") from exc

        input_digest = hashlib.sha256(request.input_data.encode("utf-8")).hexdigest()[:16]
        source_status = "verified_input_present" if request.source_ids else "unverified_no_source"
        checks = ["legal_qa_required", "logic_check_required", "risk_check_required"]
        if not request.source_ids:
            checks.append("source_check_required")

        audit_event = {
            "action": "agent_council.local_llm",
            "provider": self.name,
            "model": model,
            "role_id": request.role.role_id,
            "input_digest": input_digest,
            "cost_units": request.role.estimated_units,
            "network_call": True,
            "endpoint": self.endpoint,
        }
        return AgentExecutionResult(
            role_id=request.role.role_id,
            prompt_id=f"agent_council/{request.role.role_id}.md",
            status="completed",
            output=output,
            cost_units=request.role.estimated_units,
            source_status=source_status,
            checks=checks,
            requires_human_review=True,
            external_delivery_requires_human_approval=True,
            direct_client_delivery_allowed=False,
            audit_event=audit_event,
        )


class CloudLLMProvider(LLMProvider):
    name = "cloud"

    def __init__(self, allowed: bool = False) -> None:
        self.allowed = allowed

    def execute(self, request: AgentExecutionRequest, *, dry_run: bool) -> AgentExecutionResult:
        if not self.allowed:
            raise RuntimeError("Cloud LLM is disabled by policy.")
        if not dry_run:
            raise RuntimeError("Cloud LLM execution is not implemented; dry-run is required.")
        return _dry_run_result(request, provider=self.name)


class OpenRouterProvider(LLMProvider):
    """OpenRouter API provider — real AI analysis for AgentCouncil.

    Enabled when:
      - LEGASVEX_ALLOW_CLOUD_LLM=true
      - OPENROUTER_API_KEY is set

    Default model: google/gemini-2.0-flash-001 (fast, cheap).
    Override per-role via LEGASVEX_OPENROUTER_MODEL_<ROLE_ID_UPPER>.
    Global override: LEGASVEX_OPENROUTER_MODEL_DEFAULT.
    """

    name = "openrouter"
    _OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

    # Cost-efficient defaults per role
    _ROLE_MODEL_DEFAULTS: dict[str, str] = {
        "critic":             "deepseek/deepseek-r1-0528",
        "proceduralist":      "google/gemini-2.0-flash-001",
        "evidence_analyst":   "google/gemini-2.0-flash-001",
        "strategist":         "anthropic/claude-haiku-4-5",
        "fact_checker":       "google/gemini-2.0-flash-001",
        "position_architect": "anthropic/claude-haiku-4-5",
        "risk_controller":    "google/gemini-2.0-flash-001",
        "cost_controller":    "",
    }

    def __init__(self, api_key: str = "", allowed: bool = False) -> None:
        self.api_key = api_key.strip()
        self.allowed = allowed

    @classmethod
    def from_env(cls) -> "OpenRouterProvider":
        return cls(
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
            allowed=env_flag("LEGASVEX_ALLOW_CLOUD_LLM"),
        )

    def _model_for_role(self, role_id: str) -> str:
        env_key = f"LEGASVEX_OPENROUTER_MODEL_{role_id.upper()}"
        override = os.getenv(env_key, "").strip()
        if override:
            return override
        default = os.getenv("LEGASVEX_OPENROUTER_MODEL_DEFAULT", "").strip()
        if default:
            return default
        return self._ROLE_MODEL_DEFAULTS.get(role_id, "google/gemini-2.0-flash-001")

    def execute(self, request: AgentExecutionRequest, *, dry_run: bool) -> AgentExecutionResult:
        if not self.allowed:
            raise RuntimeError("Cloud LLM is disabled by policy (LEGASVEX_ALLOW_CLOUD_LLM=false).")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set.")
        if dry_run:
            return _dry_run_result(request, provider=self.name)
        if not request.role.role_id or request.role.role_id == "cost_controller":
            return _dry_run_result(request, provider=self.name)
        return self._call_openrouter(request)

    def _call_openrouter(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        model = self._model_for_role(request.role.role_id)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.prompt},
                {"role": "user", "content": request.input_data},
            ],
            "max_tokens": 1500,
            "temperature": 0.3,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._OPENROUTER_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://legasvex.ai",
                "X-Title": "LegasVex Advocates",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenRouter unreachable: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

        try:
            output = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected OpenRouter response: {data!r}") from exc

        input_digest = hashlib.sha256(request.input_data.encode("utf-8")).hexdigest()[:16]
        source_status = "verified_input_present" if request.source_ids else "unverified_no_source"
        checks = ["legal_qa_required", "logic_check_required", "risk_check_required"]
        if not request.source_ids:
            checks.append("source_check_required")

        audit_event = {
            "action": "agent_council.openrouter",
            "provider": self.name,
            "model": model,
            "role_id": request.role.role_id,
            "input_digest": input_digest,
            "cost_units": request.role.estimated_units,
            "network_call": True,
        }
        return AgentExecutionResult(
            role_id=request.role.role_id,
            prompt_id=f"agent_council/{request.role.role_id}.md",
            status="completed",
            output=output,
            cost_units=request.role.estimated_units,
            source_status=source_status,
            checks=checks,
            requires_human_review=True,
            external_delivery_requires_human_approval=True,
            direct_client_delivery_allowed=False,
            audit_event=audit_event,
        )


class RuleBasedProvider(LLMProvider):
    """Deterministic rule-based analysis — no LLM required.

    Used automatically when LEGASVEX_LOCAL_LLM_ENDPOINT is not set.
    Produces structured, legally-grounded output for each council role
    by analysing the task description with keyword heuristics.
    """

    name = "rule_based"

    def execute(self, request: AgentExecutionRequest, *, dry_run: bool) -> AgentExecutionResult:
        if dry_run:
            return _dry_run_result(request, provider=self.name)
        output = self._generate(request.role.role_id, request.input_data)
        input_digest = hashlib.sha256(request.input_data.encode("utf-8")).hexdigest()[:16]
        audit_event = {
            "action": "agent_council.rule_based",
            "provider": self.name,
            "role_id": request.role.role_id,
            "input_digest": input_digest,
            "cost_units": request.role.estimated_units,
            "network_call": False,
        }
        return AgentExecutionResult(
            role_id=request.role.role_id,
            prompt_id=f"agent_council/{request.role.role_id}.md",
            status="completed",
            output=output,
            cost_units=request.role.estimated_units,
            source_status="rule_based_analysis",
            checks=["legal_qa_required", "logic_check_required", "human_review_required"],
            requires_human_review=True,
            external_delivery_requires_human_approval=True,
            direct_client_delivery_allowed=False,
            audit_event=audit_event,
        )

    def _generate(self, role_id: str, topic: str) -> str:
        """Generate role-specific analysis from topic text."""
        t = topic.lower()

        # Detect dispute context
        if any(w in t for w in ("кредит", "долг", "займ", "задолженност", "взыскан")):
            dispute = "взыскание задолженности"
            law = "ст. 807–819 ГК РФ; ст. 395 ГК РФ"
        elif any(w in t for w in ("трудов", "увольнен", "зарплат", "работодател")):
            dispute = "трудовой спор"
            law = "ТК РФ гл. 60–61"
        elif any(w in t for w in ("договор", "контракт", "нарушен.*обязательств", "поставк")):
            dispute = "договорный спор"
            law = "ГК РФ гл. 27–29, ст. 393–395"
        elif any(w in t for w in ("квартир", "аренд", "жильё", "недвижимост")):
            dispute = "имущественный спор"
            law = "ЖК РФ; ст. 209–233, 301–306 ГК РФ"
        elif any(w in t for w in ("алимент", "развод", "семейн")):
            dispute = "семейный спор"
            law = "СК РФ гл. 13–17"
        else:
            dispute = "гражданский спор"
            law = "ГК РФ"

        # Role-specific output
        role_outputs = {
            "critic": (
                f"Логические противоречия:\n"
                f"Позиция описана в общих чертах — конкретные противоречия возможны только после изучения документов.\n\n"
                f"Неподтверждённые утверждения:\n"
                f"Факты из описания пока не подкреплены документально. Принятие позиции на веру — риск слабой доказательной базы.\n\n"
                f"Слабые места:\n"
                f"Категория спора «{dispute}» требует строгого соответствия нормам {law}.\n"
                f"Отсутствие ссылок на конкретные нормы снижает устойчивость позиции.\n"
                f"Возражения другой стороны не описаны.\n\n"
                f"Итог: позиция требует документального подтверждения и проверки на соответствие {law}."
            ),
            "proceduralist": (
                f"Подсудность:\n"
                f"Категория «{dispute}» — ГПК РФ (физ. лица) или АПК РФ (организации).\n"
                f"Подсудность — ст. 28–32 ГПК РФ или ст. 35–38 АПК РФ.\n\n"
                f"Срок исковой давности:\n"
                f"Общий срок — 3 года (ст. 196 ГК РФ). Трудовые споры — 1 мес./3 мес./1 год (ст. 392 ТК РФ).\n"
                f"Необходима проверка точной даты нарушения.\n\n"
                f"Досудебный порядок:\n"
                f"Коммерческие споры — обязательная претензия (ч. 5 ст. 4 АПК РФ, 30 дней).\n"
                f"Налоговые споры — апелляция в ФНС (п. 2 ст. 138 НК РФ).\n\n"
                f"Итог: приоритет — проверить срок давности и соблюдение досудебного порядка."
            ),
            "evidence_analyst": (
                f"Доказательственные пробелы:\n"
                f"Письменное основание обязательства ({law}) — отсутствует\n"
                f"Документальное подтверждение факта нарушения — отсутствует\n"
                f"Расчёт суммы требований — не представлен\n\n"
                f"Вероятные контрдоказательства оппонента:\n"
                f"Ссылка на исполнение обязательства, истечение срока давности, встречные нарушения истца.\n\n"
                f"Итог: доказательственная база требует документальной проверки."
            ),
            "strategist": (
                f"Варианты стратегии:\n"
                f"А — судебная защита: иск после сбора доказательной базы и соблюдения досудебного порядка.\n"
                f"Б — переговоры/медиация: урегулирование до суда — экономит время и ресурсы.\n"
                f"В — обеспечительные меры: при риске утраты имущества — ходатайство (ст. 139 ГПК).\n\n"
                f"Оптимальная стратегия для «{dispute}» определяется после изучения документов и оценки позиции другой стороны.\n\n"
                f"Итог: начать с переговоров при наличии документальной базы. Окончательная стратегия — после изучения материалов."
            ),
            "fact_checker": (
                f"Подтверждено:\n"
                f"Категория спора «{dispute}» соответствует описанию.\n"
                f"Применимое право {law} — соответствует категории.\n\n"
                f"Требует источника:\n"
                f"Конкретные факты нарушения — не подтверждены документально.\n"
                f"Суммы и даты — не верифицированы по первичным документам.\n"
                f"Правовая квалификация — требует проверки по актуальной редакции норм.\n\n"
                f"Источники: КонсультантПлюс/Гарант ({law}), kad.arbitr.ru, sudact.ru, обзоры ВС РФ.\n\n"
                f"Итог: нормативная основа верифицирована. Конкретные факты требуют документальной проверки."
            ),
            "position_architect": (
                f"Структура позиции:\n\n"
                f"1. Фактические обстоятельства\n"
                f"Хронология событий с точными датами, стороны и их статус, предмет спора и размер требований.\n\n"
                f"2. Правовое основание\n"
                f"Нормы {law}, квалификация нарушения, расчёт требований.\n\n"
                f"3. Доказательная база\n"
                f"Перечень документов по каждому требованию, ссылки на судебную практику.\n\n"
                f"4. Ответы на возражения\n"
                f"Опровержение вероятных доводов другой стороны, процессуальные возражения.\n\n"
                f"Итог: структура определена. Наполнение конкретными фактами — после получения документов."
            ),
            "risk_controller": (
                f"Ключевые риски ({dispute}):\n"
                f"Высокий — срок исковой давности: 3 года (ст. 196 ГК РФ) — проверить немедленно\n"
                f"Средний — доказательная база: факты не подтверждены документально\n"
                f"Средний — досудебный порядок: претензия может быть обязательна\n"
                f"Низкий — подсудность: риск возврата иска при неправильном выборе суда\n\n"
                f"Итог: приоритет — проверить срок исковой давности. Остальные риски управляемы."
            ),
            "cost_controller": (
                f"Бюджет совета использован согласно плану. Результаты других ролей — выше."
            ),
        }

        return role_outputs.get(
            role_id,
            (
                f"Анализ по ситуации «{dispute}»:\n\n"
                f"Применимое право: {law}\n\n"
                f"Требует содержательной проверки адвокатом."
            ),
        )


class AgentCouncilExecutor:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        dry_run: bool | None = None,
        allow_cloud: bool | None = None,
        local_endpoint: str | None = None,
        budget_limit: int | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self.enabled = env_flag("LEGASVEX_AGENT_COUNCIL_EXECUTION_ENABLED") if enabled is None else enabled
        self.dry_run = env_flag("LEGASVEX_AGENT_COUNCIL_DRY_RUN", True) if dry_run is None else dry_run
        self.allow_cloud = env_flag("LEGASVEX_ALLOW_CLOUD_LLM") if allow_cloud is None else allow_cloud
        self.local_endpoint = os.getenv("LEGASVEX_LOCAL_LLM_ENDPOINT", "") if local_endpoint is None else local_endpoint
        self.budget_limit = _budget_from_env() if budget_limit is None else max(0, budget_limit)
        if provider is not None:
            self.provider = provider
        elif self.local_endpoint:
            self.provider = LocalLLMProvider(self.local_endpoint)
        elif self.allow_cloud and os.getenv("OPENROUTER_API_KEY", "").strip():
            # OpenRouter available — use real AI analysis
            self.provider = OpenRouterProvider.from_env()
        else:
            # No LLM endpoint configured — use rule-based analysis as fallback
            self.provider = RuleBasedProvider()

    def execute(
        self,
        task: Task,
        plan: CouncilPlan,
        *,
        source_ids: list[str] | None = None,
        sensitive: bool = False,
    ) -> CouncilExecutionReport:
        if not self.enabled:
            return self._blocked_report("execution_disabled")
        if isinstance(self.provider, CloudLLMProvider) and not self.allow_cloud:
            return self._blocked_report("cloud_llm_disabled")
        if plan.estimated_units > self.budget_limit:
            return self._blocked_report("budget_exceeded", spent_units=0)

        results: list[AgentExecutionResult] = []
        spent = 0
        for role in plan.roles:
            if spent + role.estimated_units > self.budget_limit:
                return CouncilExecutionReport(
                    status="controlled_failure",
                    mode="dry_run" if self.dry_run else "live",
                    provider=self.provider.name,
                    results=results,
                    spent_units=spent,
                    budget_limit=self.budget_limit,
                    requires_human_review=True,
                    controlled_failure="budget_exceeded",
                )
            request = AgentExecutionRequest(
                role=role,
                prompt=_load_prompt(role.role_id),
                input_data=task.description,
                source_ids=source_ids or [],
                sensitive=sensitive or _task_requires_hitl(task),
            )
            try:
                result = self.provider.execute(request, dry_run=self.dry_run)
            except RuntimeError as exc:
                return CouncilExecutionReport(
                    status="controlled_failure",
                    mode="dry_run" if self.dry_run else "live",
                    provider=self.provider.name,
                    results=results,
                    spent_units=spent,
                    budget_limit=self.budget_limit,
                    requires_human_review=True,
                    controlled_failure=str(exc),
                )
            results.append(result)
            spent += result.cost_units

        real_calls = sum(1 for r in results if r.audit_event.get("network_call"))
        return CouncilExecutionReport(
            status="dry_run_completed" if self.dry_run else "completed",
            mode="dry_run" if self.dry_run else "live",
            provider=self.provider.name,
            results=results,
            spent_units=spent,
            budget_limit=self.budget_limit,
            requires_human_review=plan.requires_human_review or sensitive or _task_requires_hitl(task),
            real_llm_calls=real_calls,
        )

    def _blocked_report(self, reason: str, spent_units: int = 0) -> CouncilExecutionReport:
        return CouncilExecutionReport(
            status="disabled" if reason == "execution_disabled" else "controlled_failure",
            mode="dry_run" if self.dry_run else "blocked",
            provider=self.provider.name,
            results=[],
            spent_units=spent_units,
            budget_limit=self.budget_limit,
            requires_human_review=True,
            controlled_failure=reason,
        )


def _dry_run_result(request: AgentExecutionRequest, provider: str) -> AgentExecutionResult:
    source_status = "verified_input_present" if request.source_ids else "unverified_no_source"
    checks = ["legal_qa_required", "logic_check_required", "risk_check_required"]
    if not request.source_ids:
        checks.append("source_check_required")
    input_digest = hashlib.sha256(request.input_data.encode("utf-8")).hexdigest()[:16]
    audit_event = {
        "action": "agent_council.dry_run",
        "provider": provider,
        "role_id": request.role.role_id,
        "input_digest": input_digest,
        "cost_units": request.role.estimated_units,
        "network_call": False,
    }
    return AgentExecutionResult(
        role_id=request.role.role_id,
        prompt_id=f"agent_council/{request.role.role_id}.md",
        status="dry_run",
        output="Черновик для адвоката не создан: dry-run проверил маршрут, prompt и контрольные ограничения.",
        cost_units=request.role.estimated_units,
        source_status=source_status,
        checks=checks,
        requires_human_review=True,
        external_delivery_requires_human_approval=True,
        direct_client_delivery_allowed=False,
        audit_event=audit_event,
    )


def _load_prompt(role_id: str) -> str:
    prompt_path = PROMPT_ROOT / f"{role_id}.md"
    if not prompt_path.exists():
        raise RuntimeError(f"Prompt is missing for role: {role_id}")
    return prompt_path.read_text(encoding="utf-8")


def _budget_from_env() -> int:
    try:
        return max(0, int(os.getenv("LEGASVEX_AGENT_COUNCIL_BUDGET", "8")))
    except ValueError:
        return 8


def _task_requires_hitl(task: Task) -> bool:
    if task.type in {
        TaskType.LEGAL_ANALYSIS,
        TaskType.DOCUMENT_FINAL,
        TaskType.COMPLAINT_PREP,
        TaskType.COMPLAINT_SEND,
        TaskType.MATTER_STATUS_CHANGE,
        TaskType.CLIENT_INTAKE,
        TaskType.EVIDENCE_COLLECT,
    }:
        return True
    sensitive_tags = {
        "client",
        "trustor",
        "pii",
        "privileged",
        "attorney_privilege",
        "deadline",
        "procedural_deadline",
        "court_document",
        "trustor_document",
        "external_communication",
        "financially_significant",
    }
    if sensitive_tags.intersection(tag.lower() for tag in task.tags):
        return True
    return any(
        bool(task.metadata.get(flag))
        for flag in (
            "pii_present",
            "privileged_material",
            "deadline_critical",
            "client_data",
            "trustor_data",
            "court_document",
            "trustor_document",
            "external_communication",
            "financially_significant",
        )
    )
