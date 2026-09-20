from app.config import Settings, get_settings


def _storage_status(settings: Settings) -> dict:
    provider = settings.storage_provider.strip().lower()
    if provider == "s3":
        missing = settings.s3_missing_configuration()
        return {
            "provider": "s3",
            "operational": not missing,
            "production_ready": not missing,
            "missing_configuration": missing,
            "notice": "私有 S3 兼容对象存储；配置不完整时拒绝启动。",
        }
    return {
        "provider": provider or "unknown",
        "operational": provider == "local",
        "production_ready": False,
        "missing_configuration": [],
        "notice": "本地私有存储仅用于开发和测试；生产模式必须使用 s3。",
    }


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
        "resume_quality": {
            "gate_enabled": settings.resume_quality_gate_active(),
            "notice": (
                "质量硬门禁已暂时关闭，仅保留事实来源检查。"
                if not settings.resume_quality_gate_active()
                else "质量硬门禁已开启。"
            ),
        },
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
        "storage": _storage_status(settings),
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
