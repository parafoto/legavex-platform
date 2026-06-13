import os
from typing import Any, Dict, Optional

from .agent_council import AgentCouncil
from .agent_execution import AgentCouncilExecutor
from .planner import TaskPlanner
from .router import AgentRouter
from .state_machine import StateMachine, Task, TaskStatus, TaskType


def _agent_council_budget() -> int:
    try:
        return int(os.getenv("LEGASVEX_AGENT_COUNCIL_BUDGET", "8"))
    except ValueError:
        return 8


def execution_audit_value(task: Task) -> Dict[str, Any]:
    report = task.metadata.get("agent_council_execution") or {}
    return {
        "status": report.get("status", "unknown"),
        "mode": report.get("mode", "unknown"),
        "provider": report.get("provider", "unknown"),
        "spent_units": report.get("spent_units", 0),
        "budget_limit": report.get("budget_limit", 0),
        "requires_human_review": bool(report.get("requires_human_review", True)),
        "controlled_failure": report.get("controlled_failure", ""),
        "real_llm_calls": report.get("real_llm_calls", 0),
        "roles": [
            {
                "role_id": item.get("role_id", "unknown"),
                "status": item.get("status", "unknown"),
                "cost_units": item.get("cost_units", 0),
                "source_status": item.get("source_status", "unknown"),
                "requires_human_review": bool(item.get("requires_human_review", True)),
                "external_delivery_requires_human_approval": bool(
                    item.get("external_delivery_requires_human_approval", True)
                ),
            }
            for item in report.get("results", [])
        ],
    }


class Orchestrator:
    def __init__(self) -> None:
        self.state_machine = StateMachine()
        self.router = AgentRouter()
        self.planner = TaskPlanner()
        self.agent_council = AgentCouncil(budget_limit=_agent_council_budget())
        self.agent_council_executor = AgentCouncilExecutor(budget_limit=_agent_council_budget())
        self.tasks: Dict[str, Task] = {}
        self.running = True
        self.backend = os.getenv("LEGASVEX_ORCHESTRATOR_BACKEND", "memory").lower()

    async def process_command(
        self,
        command: str,
        user_id: str = "user",
        contour_scope: str = "advocate",
        tenant_scope: str = "system",
    ) -> Dict[str, Any]:
        tasks = await self.planner.create_plan(command)
        core_forbidden = {
            TaskType.COMPLAINT_SEND,
            TaskType.DOCUMENT_FINAL,
            TaskType.EVIDENCE_COLLECT,
            TaskType.MATTER_STATUS_CHANGE,
        }
        if contour_scope == "core":
            tasks = [task for task in tasks if task.type not in core_forbidden]

        for task in tasks:
            self.tasks[task.id] = task
            task.agent = self.router.route(task)
            council_plan = self.agent_council.plan(task)
            task.metadata["agent_council"] = council_plan.as_dict()
            execution_report = self.agent_council_executor.execute(task, council_plan)
            task.metadata["agent_council_execution"] = execution_report.as_dict()

            if self.state_machine.requires_human_approval(task) or council_plan.requires_human_review:
                task.requires_approval = True
                self.state_machine.transition(task, TaskStatus.PLANNED)
                self.state_machine.transition(task, TaskStatus.AWAITING_HUMAN)
            else:
                self.state_machine.transition(task, TaskStatus.PLANNED)

        await self._save_tasks(tasks, tenant_scope, contour_scope, user_id)

        return {
            "status": "planned",
            "contour_scope": contour_scope,
            "tasks": [
                {
                    "id": t.id,
                    "type": t.type.value,
                    "description": t.description,
                    "agent": t.agent,
                    "status": t.status.value,
                    "requires_approval": t.requires_approval,
                    "agent_council": t.metadata["agent_council"],
                    "agent_council_execution": t.metadata["agent_council_execution"],
                }
                for t in tasks
            ],
        }

    async def approve_task(self, task_id: str, user_id: str) -> bool:
        task = await self._get_task(task_id)
        if not task or task.status != TaskStatus.AWAITING_HUMAN:
            return False
        task.approved_by = user_id
        ok = self.state_machine.transition(task, TaskStatus.APPROVED)
        if ok:
            await self._save_task(task, actor_id=user_id, action="orchestrator.task.approved")
        return ok

    async def reject_task(self, task_id: str, reason: str = "") -> bool:
        task = await self._get_task(task_id)
        if not task or task.status != TaskStatus.AWAITING_HUMAN:
            return False
        task.error = f"Rejected: {reason}"
        ok = self.state_machine.transition(task, TaskStatus.CANCELLED)
        if ok:
            await self._save_task(task, action="orchestrator.task.rejected")
        return ok

    def get_status(self) -> Dict[str, Any]:
        statuses: Dict[str, int] = {}
        for task in self.tasks.values():
            key = task.status.value
            statuses[key] = statuses.get(key, 0) + 1

        return {
            "running": self.running,
            "backend": self.backend,
            "total_tasks": len(self.tasks),
            "statuses": statuses,
            "awaiting_human": [
                {"id": t.id, "description": t.description}
                for t in self.tasks.values()
                if t.status == TaskStatus.AWAITING_HUMAN
            ],
        }

    async def _get_task(self, task_id: str) -> Optional[Task]:
        task = self.tasks.get(task_id)
        if task is not None or self.backend != "postgres":
            return task

        from shared.db import AsyncSessionLocal
        from .task_store import TaskStore

        async with AsyncSessionLocal() as session:
            store = TaskStore(session)
            task = await store.get(task_id)
            if task is not None:
                self.tasks[task.id] = task
            return task

    async def _save_tasks(
        self,
        tasks: list[Task],
        tenant_scope: str,
        contour_scope: str,
        actor_id: str,
    ) -> None:
        if self.backend != "postgres":
            return

        from shared import audit
        from shared.db import AsyncSessionLocal
        from .task_store import TaskStore

        async with AsyncSessionLocal() as session:
            store = TaskStore(session)
            for task in tasks:
                task.metadata["tenant_scope"] = tenant_scope
                task.metadata["contour_scope"] = contour_scope
                await store.save(
                    task,
                    tenant_scope=tenant_scope,
                    contour_scope=contour_scope,
                    created_by=actor_id,
                )
                await audit.log(
                    session,
                    tenant_scope=tenant_scope,
                    contour_scope=contour_scope,
                    actor_id=actor_id,
                    action="orchestrator.task.planned",
                    entity_type="orchestrator_task",
                    entity_id=task.id,
                    new_value={
                        "task_type": task.type.value,
                        "status": task.status.value,
                        "requires_approval": task.requires_approval,
                    },
                )
                await audit.log(
                    session,
                    tenant_scope=tenant_scope,
                    contour_scope=contour_scope,
                    actor_id=actor_id,
                    action="agent_council.execution.recorded",
                    entity_type="orchestrator_task",
                    entity_id=task.id,
                    new_value=execution_audit_value(task),
                    legal_significance="draft",
                    pii_involved=bool(
                        task.metadata.get("pii_present")
                        or task.metadata.get("privileged_material")
                        or task.metadata.get("trustor_data")
                    ),
                )
            await session.commit()

    async def _save_task(
        self,
        task: Task,
        *,
        action: str,
        actor_id: str = "system",
    ) -> None:
        if self.backend != "postgres":
            return

        from shared import audit
        from shared.db import AsyncSessionLocal
        from .task_store import TaskStore

        async with AsyncSessionLocal() as session:
            store = TaskStore(session)
            tenant_scope = str(task.metadata.get("tenant_scope", "system"))
            contour_scope = str(task.metadata.get("contour_scope", "advocate"))
            await store.save(
                task,
                tenant_scope=tenant_scope,
                contour_scope=contour_scope,
                created_by=actor_id,
            )
            await audit.log(
                session,
                tenant_scope=tenant_scope,
                contour_scope=contour_scope,
                actor_id=actor_id,
                action=action,
                entity_type="orchestrator_task",
                entity_id=task.id,
                new_value={
                    "status": task.status.value,
                    "approved_by": task.approved_by,
                    "error": task.error,
                },
                legal_significance="approval",
            )
            await session.commit()
