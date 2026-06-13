from typing import List

from .state_machine import Task, TaskType


class TaskPlanner:
    async def create_plan(self, command: str, context: str = "") -> List[Task]:
        return self._fallback_plan(command)

    def _fallback_plan(self, command: str) -> List[Task]:
        cmd = command.lower()
        if "contract_risk_scan" in cmd or "risk scan" in cmd or "legal review" in cmd:
            return [Task(type=TaskType.LEGAL_ANALYSIS, description=command, priority=4)]
        if "case" in cmd or "matter" in cmd:
            return [Task(type=TaskType.CASE_CREATE, description=command, priority=3)]
        if "complaint" in cmd or "claim" in cmd:
            return [Task(type=TaskType.COMPLAINT_PREP, description=command, priority=4)]
        if "document" in cmd or "contract" in cmd:
            return [Task(type=TaskType.DOCUMENT_DRAFT, description=command, priority=3)]
        if "scooter" in cmd or "carsharing" in cmd:
            return [
                Task(
                    type=TaskType.EVIDENCE_COLLECT,
                    description=command,
                    priority=3,
                    tags=["scooter"],
                )
            ]
        if "code" in cmd:
            return [Task(type=TaskType.CODE_GENERATE, description=command, priority=2)]
        return [Task(type=TaskType.RESEARCH, description=command, priority=2)]
