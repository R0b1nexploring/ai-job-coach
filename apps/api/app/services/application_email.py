from urllib.parse import quote, urlencode

from app.providers.llm.runtime import generate_structured
from app.providers.llm.schemas import EmailDraftStructuredOutput

from .claim_entities import corpus_contains, extract_claim_entities, unsupported_chinese_claims

MAILTO_MAX_LENGTH = 2000


async def build_email_draft(
    profile,
    resume_version,
    job,
    channel,
    *,
    facts: list,
    contact: dict | None = None,
) -> dict:
    """Build text only; the product never sends mail or handles the attachment."""
    confirmed = [fact for fact in facts if fact.verification_status == "user_confirmed"]
    selected = _select_matching_facts(confirmed, job)[:3]
    name = str((contact or {}).get("name") or "求职者").strip()
    education = " / ".join(
        value
        for value in (
            str(getattr(profile, "school", "") or "").strip(),
            str(getattr(profile, "major", "") or "").strip(),
        )
        if value
    )
    subject_parts = [f"应聘{job.title}", name]
    if education:
        subject_parts.append(education)
    subject = " - ".join(subject_parts)
    fallback = {
        "introduction": (
            f"您好，我希望应聘贵司的{job.title}岗位。该投递入口来自已导入的公司渠道，"
            "岗位内容和渠道有效性仍请以贵司公开信息为准。"
        ),
        "match_points": [
            {
                "text": str(fact.value_json.get("text") or fact.label),
                "source_fact_ids": [str(fact.id)],
            }
            for fact in selected
        ],
        "closing": _closing(contact or {}),
    }
    structured, provider_name = await generate_structured(
        task="email_draft",
        system_prompt=(
            "你是中文求职邮件草稿助手。正文只写输入中已确认的事实。每条 match_point 必须"
            "逐条引用 source_fact_ids，不得补充数字、工具、组织、证书或经历；未达成目标不能"
            "写成已有能力。系统只生成草稿，不声称已经发送或附加文件。输出严格 JSON。"
        ),
        user_payload={
            "job": {"title": job.title, "company_name": job.company_name},
            "channel": {"company_name": channel.company_name, "email": channel.email},
            "confirmed_facts": [
                {
                    "id": fact.id,
                    "text": fact.value_json.get("text", ""),
                    "source_text": fact.source_text,
                }
                for fact in selected
            ],
            "contact": {key: (contact or {}).get(key, "") for key in ("name", "phone", "email")},
            "mock_response": fallback,
        },
        response_model=EmailDraftStructuredOutput,
    )
    content = structured.model_dump()
    # Keep the framing deterministic so unguarded LLM prose cannot introduce claims.
    content["introduction"] = fallback["introduction"]
    content["closing"] = fallback["closing"]
    guard_status, issues = guard_email_match_points(content["match_points"], confirmed)
    fallback_used = provider_name != "compatible"
    minimum_points = min(2, len(selected))
    if guard_status == "blocked" or len(content["match_points"]) < minimum_points:
        content = fallback
        fallback_used = True
        guard_status, issues = guard_email_match_points(content["match_points"], confirmed)

    points_text = "\n".join(f"• {item['text']}" for item in content["match_points"])
    body = "\n\n".join(
        part for part in (content["introduction"], points_text, content["closing"]) if part
    )
    warnings = ["这是邮件草稿，系统不会代发邮件，也不会自动附加简历。"]
    if len(content["match_points"]) < 2:
        warnings.append("已确认的岗位匹配事实不足 2 条，请人工检查并补充后再发送。")
    if resume_version.kind == "target" and resume_version.unachieved_count > 0:
        warnings.append(
            f"附件含 {resume_version.unachieved_count} 条未达成内容；邮件正文只引用已达成事实。"
        )
    attachment_hint = f"请手动附加经审核的 DOCX 简历：{resume_version.title}"
    mailto_url = _mailto(channel.email, subject, body) if guard_status == "passed" else ""
    if guard_status != "passed":
        warnings.append("邮件匹配点未通过事实校验，请先确认至少一条相关事实。")
    elif not mailto_url:
        warnings.append("正文较长，未生成 mailto 链接；请复制主题和正文到邮件客户端。")
    return {
        "to": channel.email,
        "subject": subject,
        "body": body,
        "attachment_hint": attachment_hint,
        "mailto_url": mailto_url,
        "warnings": warnings,
        "match_points": content["match_points"],
        "guard_status": guard_status,
        "guard_issues": issues,
        "provider": provider_name,
        "fallback_used": fallback_used,
    }


def guard_email_match_points(points: list[dict], facts: list) -> tuple[str, list[str]]:
    facts_by_id = {
        str(fact.id): fact for fact in facts if fact.verification_status == "user_confirmed"
    }
    issues = []
    if not points:
        issues.append("邮件至少需要一条可溯源的匹配点")
    if len(points) > 3:
        issues.append("邮件匹配点不能超过 3 条")
    for index, point in enumerate(points):
        text = str(point.get("text") or "")
        if not text.strip():
            issues.append(f"第 {index + 1} 条匹配点内容不能为空")
            continue
        ids = [str(value) for value in point.get("source_fact_ids") or []]
        if not ids or any(value not in facts_by_id for value in ids):
            issues.append(f"第 {index + 1} 条匹配点引用了未确认事实")
            continue
        corpus = " ".join(
            " ".join(
                [
                    str(facts_by_id[value].value_json or {}),
                    str(facts_by_id[value].source_text or ""),
                    str(facts_by_id[value].organization or ""),
                    str(facts_by_id[value].role_title or ""),
                ]
            )
            for value in ids
        )
        for entity in extract_claim_entities(text):
            if not corpus_contains(corpus, entity):
                issues.append(f"第 {index + 1} 条匹配点包含无来源实体：{entity}")
        issues.extend(
            f"第 {index + 1} 条匹配点包含无来源中文主张：{claim}"
            for claim in unsupported_chinese_claims(text, corpus)
        )
    return ("blocked" if issues else "passed", sorted(set(issues)))


def _select_matching_facts(facts: list, job) -> list:
    requirements = [
        str(value).casefold()
        for value in [*(job.must_have_json or []), *(job.keywords_json or [])]
        if str(value).strip()
    ]

    def rank(fact):
        text = str(fact.value_json.get("text") or fact.label).casefold()
        hits = sum(requirement in text or text in requirement for requirement in requirements)
        category = {"employment": 3, "projects": 2, "skills": 1}.get(fact.category, 0)
        return hits, category

    return sorted(facts, key=rank, reverse=True)


def _closing(contact: dict) -> str:
    details = [
        value
        for value in (
            str(contact.get("phone") or "").strip(),
            str(contact.get("email") or "").strip(),
        )
        if value
    ]
    suffix = f"联系方式：{' / '.join(details)}。" if details else "联系方式请以简历为准。"
    return f"简历请见手动添加的附件，感谢您审阅。{suffix}"


def _mailto(to: str, subject: str, body: str) -> str:
    query = urlencode({"subject": subject, "body": body}, quote_via=quote)
    value = f"mailto:{quote(to, safe='@')}?{query}"
    return value if len(value) <= MAILTO_MAX_LENGTH else ""
