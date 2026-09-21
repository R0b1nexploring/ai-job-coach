"""Contract tests for the canonical task status vocabulary (task 17.2)."""

import pytest

from app.services.task_status import (
    BUNDLE_STATUSES,
    TASK_ACTIVE_STATUSES,
    TASK_STATUSES,
    TASK_TERMINAL_STATUSES,
    TASK_TYPES,
    bundle_status_for_task,
    is_task_terminal,
    task_status_for_bundle,
)


def test_task_and_bundle_vocabularies_stay_closed():
    assert TASK_STATUSES == {"queued", "running", "succeeded", "degraded", "failed"}
    assert BUNDLE_STATUSES == {"queued", "generating", "ready", "degraded", "failed"}
    assert TASK_ACTIVE_STATUSES | TASK_TERMINAL_STATUSES == TASK_STATUSES
    assert TASK_ACTIVE_STATUSES & TASK_TERMINAL_STATUSES == set()
    assert TASK_TYPES == {
        "target_profile",
        "resume_parse",
        "material_clarify",
        "resume_bundle",
        "interview_guide",
        "pdf_export",
    }


@pytest.mark.parametrize(
    ("task_status", "bundle_status"),
    [
        ("queued", "queued"),
        ("running", "generating"),
        ("succeeded", "ready"),
        ("degraded", "degraded"),
        ("failed", "failed"),
    ],
)
def test_status_mapping_round_trips(task_status, bundle_status):
    assert bundle_status_for_task(task_status) == bundle_status
    assert task_status_for_bundle(bundle_status) == task_status


def test_unknown_statuses_are_rejected_instead_of_defaulted():
    with pytest.raises(ValueError):
        bundle_status_for_task("generating")
    with pytest.raises(ValueError):
        task_status_for_bundle("succeeded")
    with pytest.raises(ValueError):
        bundle_status_for_task("")


def test_terminal_classification_matches_delivery_states():
    assert is_task_terminal("succeeded") is True
    assert is_task_terminal("degraded") is True
    assert is_task_terminal("failed") is True
    assert is_task_terminal("queued") is False
    assert is_task_terminal("running") is False
