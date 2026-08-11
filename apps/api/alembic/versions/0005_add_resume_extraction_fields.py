"""Add structured resume contact and clarification fields."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0005_add_resume_extraction_fields"
down_revision = "0004_add_capability_targets"
branch_labels = None
depends_on = None

COLUMNS = (
    ("contact_json", sa.JSON(), "{}"),
    ("missing_information_json", sa.JSON(), "[]"),
)


def upgrade():
    existing = {column["name"] for column in inspect(op.get_bind()).get_columns("resumes")}
    for name, type_, default in COLUMNS:
        if name not in existing:
            op.add_column(
                "resumes",
                sa.Column(name, type_, nullable=False, server_default=default),
            )


def downgrade():
    existing = {column["name"] for column in inspect(op.get_bind()).get_columns("resumes")}
    with op.batch_alter_table("resumes") as batch:
        for name, _type, _default in reversed(COLUMNS):
            if name in existing:
                batch.drop_column(name)
