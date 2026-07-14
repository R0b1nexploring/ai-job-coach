from .fact_guard import guard_content


def generate_resume(facts: list, job, inject_unverified: bool = False):
    confirmed = [f for f in facts if f.verification_status == "user_confirmed"]
    items = []
    for fact in confirmed[:8]:
        text = str(fact.value_json.get("text", fact.label))
        items.append({"text": text, "source_fact_ids": [fact.id], "target_requirement_ids": [], "new_claims": []})
    if inject_unverified:
        items.append({"text": "优化流程并提升效率 30%", "source_fact_ids": [confirmed[0].id] if confirmed else [], "target_requirement_ids": [], "new_claims": []})
    content = {"headline": f"{job.title}方向求职简历", "sections": [{"name": "相关经历", "items": items}], "excluded_gaps": [k for k in (job.keywords_json or []) if not any(k.lower() in str(f.value_json).lower() for f in confirmed)]}
    status, new_claims = guard_content(content, confirmed)
    return content, status, new_claims

