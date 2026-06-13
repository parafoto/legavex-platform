from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class TaskStatus(Enum):
    CREATED = "created"
    PLANNED = "planned"
    AWAITING_HUMAN = "awaiting_human"
    APPROVED = "approved"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(Enum):
    LEGAL_ANALYSIS = "legal_analysis"
    DOCUMENT_DRAFT = "document_draft"
    DOCUMENT_FINAL = "document_final"
    COMPLAINT_PREP = "complaint_prep"
    COMPLAINT_SEND = "complaint_send"
    EVIDENCE_COLLECT = "evidence_collect"
    CASE_CREATE = "case_create"
    CASE_UPDATE = "case_update"
    MATTER_STATUS_CHANGE = "matter_status_change"
    CLIENT_INTAKE = "client_intake"
    CODE_GENERATE = "code_generate"
    CODE_REFACTOR = "code_refactor"
    ADMIN = "admin"
    RESEARCH = "research"


@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: TaskType = TaskType.ADMIN
    description: str = ""
    agent: str = ""
    status: TaskStatus = TaskStatus.CREATED
    priority: int = 2
    country: str = "ru"
    tags: List[str] = field(default_factory=list)
    requires_approval: bool = False
    approved_by: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class StateMachine:
    VALID_TRANSITIONS = {
        TaskStatus.CREATED: [TaskStatus.PLANNED, TaskStatus.CANCELLED],
        TaskStatus.PLANNED: [TaskStatus.AWAITING_HUMAN, TaskStatus.ASSIGNED, TaskStatus.CANCELLED],
        TaskStatus.AWAITING_HUMAN: [TaskStatus.APPROVED, TaskStatus.CANCELLED],
        TaskStatus.APPROVED: [TaskStatus.ASSIGNED, TaskStatus.CANCELLED],
        TaskStatus.ASSIGNED: [TaskStatus.IN_PROGRESS, TaskStatus.FAILED],
        TaskStatus.IN_PROGRESS: [TaskStatus.COMPLETED, TaskStatus.FAILED],
        TaskStatus.FAILED: [TaskStatus.CANCELLED],
    }

    HITL_TRIGGERS = {
        TaskType.LEGAL_ANALYSIS: True,
        TaskType.COMPLAINT_SEND: True,
        TaskType.DOCUMENT_FINAL: True,
        TaskType.MATTER_STATUS_CHANGE: True,
    }

    def can_transition(self, task: Task, new_status: TaskStatus) -> bool:
        return new_status in self.VALID_TRANSITIONS.get(task.status, [])

    def transition(self, task: Task, new_status: TaskStatus) -> bool:
        if not self.can_transition(task, new_status):
            return False
        task.status = new_status
        if new_status == TaskStatus.IN_PROGRESS:
            task.started_at = datetime.now().isoformat()
        if new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.completed_at = datetime.now().isoformat()
        return True

    def requires_human_approval(self, task: Task) -> bool:
        return self.HITL_TRIGGERS.get(task.type, False)
