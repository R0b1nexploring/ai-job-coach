from app.config import get_settings


def provider_status() -> dict:
    settings = get_settings()
    llm_name = settings.llm_provider.strip().lower()
    required = {
        "LLM_API_BASE_URL": bool(settings.llm_api_base_url.strip()),
        "LLM_API_KEY": bool(settings.llm_api_key.get_secret_value().strip()),
        "LLM_MODEL_CHEAP 或 LLM_MODEL": bool(settings.model_for("jd_normalize")),
        "LLM_MODEL_STRONG 或 LLM_MODEL": bool(settings.model_for("resume_rewrite")),
    }
    if llm_name == "mock":
        llm = {
            "provider": "mock",
            "operational": True,
            "uses_fallback": False,
            "missing_configuration": [],
            "notice": "当前使用本地稳定 Mock，不调用外部模型。",
        }
    elif llm_name == "compatible":
        missing = [name for name, present in required.items() if not present]
        llm = {
            "provider": "compatible",
            "operational": not missing,
            "uses_fallback": bool(missing),
            "missing_configuration": missing,
            "notice": "配置完整时调用兼容 Chat Completions 的模型；失败会回退 Mock。",
        }
    elif llm_name == "mock_fallback":
        llm = {
            "provider": "mock_fallback",
            "operational": True,
            "uses_fallback": True,
            "missing_configuration": [],
            "notice": "当前显式使用本地 Mock 回退，不调用外部模型。",
        }
    else:
        llm = {
            "provider": llm_name or "unknown",
            "operational": False,
            "uses_fallback": True,
            "missing_configuration": ["LLM_PROVIDER"],
            "notice": "未知 Provider 将回退 Mock。",
        }
    return {
        "llm": llm,
        "jobs": {
            "operational": True,
            "providers": [
                "sample",
                "public_catalog",
                "greenhouse",
                "lever",
                "public_jsonld",
            ],
            "public_jsonld_configured": bool(settings.allowed_job_source_hosts()),
            "notice": "只读取公开企业职位接口和白名单 JSON-LD；外部失败时回退本地样例。",
        },
        "storage": {
            "provider": settings.storage_provider,
            "operational": settings.storage_provider == "local",
            "production_ready": False,
            "notice": (
                "当前仅实现本地私有存储；生产模式会拒绝启动，直至接入真正的私有对象存储。"
            ),
        },
        "payment": {
            "provider": settings.payment_provider,
            "operational": settings.payment_provider == "disabled",
            "notice": "MVP-1 按规格禁用真实支付。",
        },
        "retention": {
            "days": settings.data_retention_days,
            "deletion_grace_days": settings.deletion_grace_days,
            "job_stale_days": settings.job_stale_days,
        },
    }
