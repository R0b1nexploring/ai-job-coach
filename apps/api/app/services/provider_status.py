from app.config import get_settings


def provider_status() -> dict:
    settings = get_settings()
    llm_name = settings.llm_provider.strip().lower()
    required = {
        "LLM_API_BASE_URL": bool(settings.llm_api_base_url.strip()),
        "LLM_API_KEY": bool(settings.llm_api_key.strip()),
        "LLM_MODEL": bool(settings.llm_model.strip()),
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
        "ocr": {
            "provider": "rapidocr",
            "operational": True,
            "uses_fallback": False,
            "notice": "JD 截图在本地识别，不上传到第三方；失败时可使用用户补充文字。",
        },
        "jobs": {
            "operational": True,
            "providers": ["sample", "public_catalog", "greenhouse", "lever"],
            "notice": "只读取公开企业职位接口；外部失败时回退本地样例。",
        },
        "storage": {
            "provider": settings.storage_provider,
            "operational": settings.storage_provider == "local",
            "notice": "当前为本地私有存储；正式运营需切换私有对象存储。",
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
