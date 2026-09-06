from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import current_user
from app.models.entities import User
from app.services.experience_service import (
    ALLOWED_KINDS,
    confirm_experience,
    copy_template,
    create_user_experience,
    delete_user_experience,
    generate_material_clarifications,
    list_experience,
    update_user_experience,
    visible_experience,
)

from .common import dump, listed

router = APIRouter(prefix="/api", tags=["experience"])


MaterialKind = Literal[
    "education",
    "internship",
    "employment",
    "project",
    "research",
    "competition",
    "award",
    "certificate",
    "skill",
]


class ExperienceIn(BaseModel):
    kind: MaterialKind
    title: str = Field(min_length=1, max_length=200)
    organization: str = Field(default="", max_length=200)
    role_title: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=100)
    start_date: str = Field(default="", max_length=10)
    end_date: str = Field(default="", max_length=10)
    summary: str = Field(default="", max_length=5000)
    bullets_json: list[str] = Field(default_factory=list)
    skills_json: list[str] = Field(default_factory=list)
    details_json: dict[str, str] = Field(default_factory=dict)


class ExperiencePatchIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    role_title: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=100)
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    summary: str | None = Field(default=None, max_length=5000)
    bullets_json: list[str] | None = None
    skills_json: list[str] | None = None
    details_json: dict[str, str] | None = None


@router.get("/experience")
async def experience_list(
    kind: str = Query(default="", pattern="^(|education|internship|employment|project|research|competition|award|certificate|skill)$"),
    source: str = Query(default="", pattern="^(|user_added|original_resume|template)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = list_experience(db, user, kind=kind, source=source)
    return listed([_dump_entry(row, user.id) for row in rows], page_size=200)


@router.post("/experience", status_code=201)
async def experience_create(
    data: ExperienceIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = create_user_experience(db, user, data.model_dump())
    db.commit()
    db.refresh(row)
    return _dump_entry(row, user.id)


@router.post("/experience/from-template/{template_id}", status_code=201)
async def experience_from_template(
    template_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = copy_template(db, user, template_id)
    db.commit()
    db.refresh(row)
    return _dump_entry(row, user.id)


@router.get("/experience/{entry_id}")
async def experience_detail(
    entry_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return _dump_entry(visible_experience(db, user, entry_id), user.id)


@router.patch("/experience/{entry_id}")
async def experience_update(
    entry_id: str,
    data: ExperiencePatchIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = update_user_experience(
        db, user, entry_id, data.model_dump(exclude_unset=True)
    )
    db.commit()
    db.refresh(row)
    return _dump_entry(row, user.id)


@router.post("/experience/{entry_id}/clarifications")
async def experience_clarifications(
    entry_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = await generate_material_clarifications(db, user, entry_id)
    db.commit()
    db.refresh(row)
    return _dump_entry(row, user.id)


@router.post("/experience/{entry_id}/confirm")
async def experience_confirm(
    entry_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = confirm_experience(db, user, entry_id)
    db.commit()
    db.refresh(row)
    return _dump_entry(row, user.id)


@router.delete("/experience/{entry_id}")
async def experience_delete(
    entry_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    delete_user_experience(db, user, entry_id)
    db.commit()
    return {"status": "deleted"}


def _dump_entry(row, user_id: str) -> dict:
    payload = dump(row)
    payload["is_template"] = row.owner_user_id is None
    payload["is_own"] = row.owner_user_id == user_id
    payload["linked_to_facts"] = bool(row.linked_fact_id) or row.status == "confirmed"
    payload["allowed_kinds"] = sorted(ALLOWED_KINDS)
    return payload
