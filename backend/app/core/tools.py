from enum import StrEnum


class ToolStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ToolRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalMode(StrEnum):
    NEVER = "never"
    ALWAYS = "always"


class ToolRunStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


TERMINAL_TOOL_RUN_STATUSES = frozenset(
    {
        ToolRunStatus.SUCCEEDED,
        ToolRunStatus.FAILED,
        ToolRunStatus.REJECTED,
    }
)
