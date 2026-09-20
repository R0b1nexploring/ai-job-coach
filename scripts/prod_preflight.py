"""Production preflight: verify real dependencies, not just configuration.

Run inside the API container after deploy:

    docker compose -f docker-compose.prod.yml exec api python scripts/prod_preflight.py

Exits non-zero on the first hard failure so the deploy can be gated on it.
Add --check-llm to also make one tiny model call (costs money).
"""

from __future__ import annotations

import argparse

from sqlalchemy import text


def _fail(message: str) -> None:
    print(f"[preflight] FAIL: {message}")
    raise SystemExit(1)


def check_settings() -> None:
    from app.config import get_settings

    settings = get_settings()  # Raises UnsafeConfigurationError when production is misconfigured.
    print(
        "[preflight] settings ok "
        f"(env={settings.app_env}, storage={settings.storage_provider}, db=postgresql)"
    )


def check_database() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from app.config import get_settings
    from app.database import make_engine

    engine = make_engine(get_settings().resolved_database_url())
    try:
        with engine.connect() as connection:
            current = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()

    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    head = ScriptDirectory.from_config(config).get_current_head()
    if current != head:
        _fail(f"数据库迁移版本 {current!r} 与 head {head!r} 不一致，请先运行迁移")
    print(f"[preflight] database ok (revision={current})")


def check_storage() -> None:
    from app.providers.storage.runtime import get_storage

    storage = get_storage()
    key = storage.save(b"preflight-probe", ".txt")
    try:
        if storage.read(key) != b"preflight-probe":
            _fail("对象存储写入后读回内容不一致")
    finally:
        storage.delete(key)
    print("[preflight] object storage ok (save/read/delete)")


def check_pdf() -> None:
    import asyncio

    from app.services.pdf_export import _chromium_pdf, converter_available

    if not converter_available():
        _fail("没有可用的 PDF 转换器（需要 Chromium）")
    pdf = asyncio.run(_chromium_pdf("<html><body><p>preflight</p></body></html>"))
    if not pdf or not pdf.startswith(b"%PDF"):
        _fail("Chromium 未能生成 PDF")
    print("[preflight] pdf converter ok (chromium)")


def check_llm(call: bool) -> None:
    from app.config import get_settings

    settings = get_settings()
    model = settings.model_for("resume_rewrite")
    if not (settings.llm_api_base_url.strip() and settings.llm_api_key.get_secret_value().strip()):
        _fail("LLM 地址或密钥缺失")
    if not call:
        print(f"[preflight] llm config ok (model={model}); pass --check-llm to call it")
        return

    import asyncio

    from app.providers.llm.runtime import configured_provider
    from app.providers.llm.schemas import JobStructuredOutput

    async def probe() -> str:
        # Call the configured provider directly so a failure is not masked by
        # the runtime's Mock fallback.
        provider, name = configured_provider()
        await provider.generate_structured(
            task="jd_normalize",
            system_prompt="把 JD 提取为严格 JSON。",
            user_payload={"raw_jd": "招聘机械设计工程师，要求熟悉 SolidWorks。"},
            response_model=JobStructuredOutput,
        )
        return name

    try:
        provider_name = asyncio.run(probe())
    except Exception as exc:  # noqa: BLE001 - report any provider failure, then stop
        _fail(f"LLM 调用失败：{type(exc).__name__}")
    print(f"[preflight] llm call ok (provider={provider_name}, model={model})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-llm", action="store_true")
    args = parser.parse_args()

    check_settings()
    check_database()
    check_storage()
    check_pdf()
    check_llm(args.check_llm)
    print("[preflight] all checks passed")


if __name__ == "__main__":
    main()
