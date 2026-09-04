from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.providers.llm.schemas import ResumeStructuredV2Output
from pydantic import ValidationError

MAX_RESUME_LINES = 48
MAX_BULLET_CHARS = 120


class ResumeWorkflowError(ValueError):
    """A safe structural error that never includes resume body text."""

    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def load_content(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResumeWorkflowError([f"input: {type(exc).__name__}"]) from exc
    if not isinstance(value, dict):
        raise ResumeWorkflowError(["input: root must be a JSON object"])
    return value


def validate_content(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    issues: list[str] = []
    try:
        model = ResumeStructuredV2Output.model_validate(raw)
    except ValidationError as exc:
        for item in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in item.get("loc", ())) or "root"
            issues.append(f"{location}: {item.get('type', 'invalid')}")
        raise ResumeWorkflowError(issues) from exc

    content = model.model_dump()
    kind = content["kind"]
    contact = content.get("contact") or {}
    if not str(contact.get("name") or "").strip():
        issues.append("contact.name: required")
    if not (str(contact.get("phone") or "").strip() or str(contact.get("email") or "").strip()):
        issues.append("contact: phone or email required")

    bullet_count = 0
    target_count = 0
    for section_index, section in enumerate(content.get("sections") or []):
        if not str(section.get("name") or "").strip():
            issues.append(f"sections.{section_index}.name: required")
        for item_index, item in enumerate(section.get("items") or []):
            for bullet_index, bullet in enumerate(item.get("bullets") or []):
                bullet_count += 1
                pointer = (
                    f"sections.{section_index}.items.{item_index}.bullets.{bullet_index}"
                )
                text = str(bullet.get("text") or "").strip()
                if len(text) > MAX_BULLET_CHARS:
                    issues.append(f"{pointer}.text: exceeds {MAX_BULLET_CHARS} characters")
                if bullet.get("new_claims"):
                    issues.append(f"{pointer}.new_claims: must be empty")
                fact_ids = bullet.get("source_fact_ids") or []
                target_ids = bullet.get("source_target_ids") or []
                if bullet.get("achieved") is False:
                    target_count += 1
                    if kind != "target":
                        issues.append(f"{pointer}.achieved: submittable bullets must be true")
                    if not target_ids:
                        issues.append(f"{pointer}.source_target_ids: required when unachieved")
                    if fact_ids:
                        issues.append(f"{pointer}.source_fact_ids: forbidden when unachieved")
                else:
                    if not fact_ids:
                        issues.append(f"{pointer}.source_fact_ids: required when achieved")
                    if target_ids:
                        issues.append(f"{pointer}.source_target_ids: forbidden when achieved")

    if bullet_count == 0:
        issues.append("sections: at least one bullet is required")
    if kind == "submittable" and target_count:
        issues.append("kind: submittable content cannot contain learning targets")

    estimated_lines = estimate_lines(content)
    if estimated_lines > MAX_RESUME_LINES:
        issues.append(
            f"page_budget: estimated {estimated_lines} lines exceeds {MAX_RESUME_LINES}"
        )
    if issues:
        raise ResumeWorkflowError(issues)
    return content, {
        "sections": len(content.get("sections") or []),
        "bullets": bullet_count,
        "unachieved": target_count,
        "estimated_lines": estimated_lines,
    }


def estimate_lines(content: dict[str, Any]) -> int:
    """Conservative text budget aligned with the product's one-page contract."""
    lines = 4
    for section in content.get("sections") or []:
        items = section.get("items") or []
        if not items:
            continue
        lines += 1
        tags = section.get("presentation") == "tags"
        if tags:
            tag_chars = sum(
                len(str(bullet.get("text") or "")) + 3
                for item in items
                for bullet in item.get("bullets") or []
            )
            lines += max(1, math.ceil(tag_chars / 58))
            continue
        for item in items:
            if any(
                str(item.get(field) or "").strip()
                for field in ("organization", "role_title", "start_date", "end_date")
            ):
                lines += 1
            for bullet in item.get("bullets") or []:
                marker_chars = 12 if bullet.get("achieved") is False else 0
                lines += max(
                    1,
                    math.ceil((len(str(bullet.get("text") or "")) + marker_chars) / 46),
                )
        lines += 1
    return lines
