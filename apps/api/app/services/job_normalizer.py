import hashlib
import re


KEYWORDS = ["设备点检", "SOP", "CAD", "SolidWorks", "机械", "本科", "轮班", "出差", "维护", "跨部门"]


def normalize_job(raw_jd: str, title: str = "", company_name: str = "", city: str = "") -> dict:
    lines = [x.strip(" -•\t") for x in raw_jd.splitlines() if x.strip()]
    inferred_title = title or next((x for x in lines if "工程师" in x), "待确认岗位")
    must = [x for x in lines if re.search(r"要求|本科|专业|必须|熟悉|接受", x)][:8]
    responsibilities = [x for x in lines if re.search(r"负责|协助|维护|编制|跟进", x)][:8]
    nice = [x for x in lines if re.search(r"优先|加分", x)][:5]
    keywords = [k for k in KEYWORDS if k.lower() in raw_jd.lower()]
    work = [x for x in lines if re.search(r"轮班|出差|工厂", x)][:5]
    return {
        "title": inferred_title,
        "company_name": company_name or "待确认公司",
        "city": city,
        "responsibilities": responsibilities,
        "must_have": must,
        "nice_to_have": nice,
        "keywords": keywords,
        "work_conditions": work,
        "uncertain_fields": [k for k, v in {"company_name": company_name, "city": city}.items() if not v],
        "content_hash": hashlib.sha256(raw_jd.strip().encode()).hexdigest(),
    }

