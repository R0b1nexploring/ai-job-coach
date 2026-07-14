# Project instructions

- `PROJECT_SPEC.md` and `docs/product-spec.md` are the only product requirements.
- Run the relevant tests after every change.
- Never treat AI-generated text as a verified fact.
- Every database schema change requires an Alembic migration.
- Every external service needs a Base Provider and a safe local fallback; payment uses Disabled Provider in MVP-1.
- Never put secrets or complete resume contents in code or logs.
- User-facing copy is clear Chinese; code identifiers are English.
