"""Canonical task run-state vocabulary and its legacy bundle projection.

The unified task record is the long-term owner of claim and run state. Until the
claim authority is switched over (tasks 17.6-17.7), existing
``resume_bundle_runs`` rows stay readable through one explicit mapping rather
than two competing status dialects.

Bundle compatibility projection (PROJECT_SPEC 29.3):

    queued    -> queued
    running   -> generating
    succeeded -> ready
    degraded  -> degraded
    failed    -> failed
"""

TASK_QUEUED = "queued"
TASK_RUNNING = "running"
TASK_SUCCEEDED = "succeeded"
TASK_DEGRADED = "degraded"
TASK_FAILED = "failed"

TASK_STATUSES = frozenset(
    {TASK_QUEUED, TASK_RUNNING, TASK_SUCCEEDED, TASK_DEGRADED, TASK_FAILED}
)
TASK_ACTIVE_STATUSES = frozenset({TASK_QUEUED, TASK_RUNNING})
TASK_TERMINAL_STATUSES = frozenset({TASK_SUCCEEDED, TASK_DEGRADED, TASK_FAILED})

# Task types the unified contract accepts. Anything else is rejected at the
# API boundary instead of being silently routed to a default consumer.
TASK_TYPES = frozenset(
    {
        "target_profile",
        "resume_parse",
        "material_clarify",
        "resume_bundle",
        "interview_guide",
        "pdf_export",
    }
)

# ``adjust_length`` is a scope of ``resume_bundle``, not a separate task type.
RESUME_BUNDLE_OPERATIONS = frozenset({"create", "adjust_length", "regenerate"})

BUNDLE_STATUSES = frozenset({"queued", "generating", "ready", "degraded", "failed"})

_TASK_TO_BUNDLE = {
    TASK_QUEUED: "queued",
    TASK_RUNNING: "generating",
    TASK_SUCCEEDED: "ready",
    TASK_DEGRADED: "degraded",
    TASK_FAILED: "failed",
}
_BUNDLE_TO_TASK = {value: key for key, value in _TASK_TO_BUNDLE.items()}


def bundle_status_for_task(status: str) -> str:
    """Project a unified task status onto the legacy bundle status."""
    normalized = str(status or "").strip().lower()
    try:
        return _TASK_TO_BUNDLE[normalized]
    except KeyError:
        raise ValueError(f"未知任务状态：{normalized or 'empty'}") from None


def task_status_for_bundle(status: str) -> str:
    """Map a stored legacy bundle status onto the unified task status."""
    normalized = str(status or "").strip().lower()
    try:
        return _BUNDLE_TO_TASK[normalized]
    except KeyError:
        raise ValueError(f"未知简历包状态：{normalized or 'empty'}") from None


def is_task_terminal(status: str) -> bool:
    return str(status or "").strip().lower() in TASK_TERMINAL_STATUSES
