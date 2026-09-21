from app.services.claim_entities import (
    corpus_contains,
    extract_claim_entities,
    unsupported_chinese_claims,
)


def guard_content(
    content: dict,
    confirmed_facts: list,
    targets: list | None = None,
    mode: str = "submittable",
) -> dict:
    """Validate every resume bullet against only the sources explicitly cited by that bullet."""
    if mode not in {"submittable", "target"}:
        raise ValueError("mode 必须是 submittable 或 target")
    facts_by_id = {
        str(fact.id): fact
        for fact in confirmed_facts
        if getattr(fact, "id", None)
        and getattr(fact, "verification_status", "user_confirmed") == "user_confirmed"
    }
    targets_by_id = {
        str(target.id): target
        for target in targets or []
        if getattr(target, "id", None) and getattr(target, "status", "pending") != "achieved"
    }
    all_issues: list[str] = []
    item_results = []
    unachieved_count = 0

    for location, bullet in _iter_bullets(content):
        issues = []
        fact_ids = _source_ids(bullet, "source_fact_ids")
        target_ids = list(
            dict.fromkeys(
                _source_ids(bullet, "source_target_ids")
                + _source_ids(bullet, "requirement_ids")
            )
        )
        if not fact_ids and not target_ids:
            issues.append("缺少事实来源")

        invalid_fact_ids = [fact_id for fact_id in fact_ids if fact_id not in facts_by_id]
        if invalid_fact_ids:
            issues.append("引用了未确认或不属于当前用户的事实")

        # ``requirement_ids`` records which job requirement a bullet proves,
        # which the v3 contract sets on every supported submittable bullet.
        # Only ``source_target_ids`` means "this bullet is about an unachieved
        # target", so only that may block a submittable resume.
        cited_source_target_ids = _source_ids(bullet, "source_target_ids")
        invalid_target_ids = [
            target_id
            for target_id in cited_source_target_ids
            if target_id not in targets_by_id
        ]
        if cited_source_target_ids and mode == "submittable":
            issues.append("可投递简历不得引用未达成目标")
        elif invalid_target_ids:
            issues.append("引用了不属于当前用户或已经失效的学习目标")

        valid_target_ids = [target_id for target_id in target_ids if target_id in targets_by_id]
        if mode == "target" and valid_target_ids:
            unachieved_count += 1
            if bullet.get("achieved") is not False:
                issues.append("未达成条目缺少 achieved 标记")

        # Keep the source fields separate as well as joined: the Chinese-claim
        # check needs field boundaries, because a joined string can split a
        # single field mid-sentence and produce fragments that match a claim by
        # accident.
        source_fields = [
            *(
                _fact_fields(facts_by_id[fact_id])
                for fact_id in fact_ids
                if fact_id in facts_by_id
            ),
            *(
                [_target_corpus(targets_by_id[target_id])]
                for target_id in valid_target_ids
                if mode == "target"
            ),
        ]
        fields = [value for group in source_fields for value in group if value]
        corpus = " ".join(fields)
        for entity in extract_claim_entities(str(bullet.get("text") or "")):
            if not corpus_contains(corpus, entity):
                issues.append(f"未经来源支持的实体：{entity}")
        issues.extend(
            f"未经来源支持的中文主张：{claim}"
            for claim in unsupported_chinese_claims(str(bullet.get("text") or ""), fields)
        )
        issues.extend(
            f"显式标记的新主张：{claim}"
            for claim in bullet.get("new_claims", [])
            if str(claim).strip()
        )
        issues = list(dict.fromkeys(issues))
        all_issues.extend(issues)
        item_results.append(
            {
                **location,
                "status": "blocked" if issues else "passed",
                "issues": issues,
                "source_fact_ids": fact_ids,
                "source_target_ids": target_ids,
                "achieved": bullet.get("achieved"),
            }
        )

    if not item_results:
        all_issues.append("简历内容没有可校验条目")
    issues = sorted(set(all_issues))
    return {
        "status": "blocked" if issues else "passed",
        "issues": issues,
        "unachieved_count": unachieved_count,
        "items": item_results,
    }


def _iter_bullets(content: dict):
    for section_index, section in enumerate(content.get("sections") or []):
        for item_index, item in enumerate(section.get("items") or []):
            bullets = item.get("bullets")
            if isinstance(bullets, list):
                for bullet_index, bullet in enumerate(bullets):
                    if isinstance(bullet, dict):
                        yield {
                            "section_index": section_index,
                            "item_index": item_index,
                            "bullet_index": bullet_index,
                        }, bullet
            elif isinstance(item, dict):
                yield {
                    "section_index": section_index,
                    "item_index": item_index,
                    "bullet_index": None,
                }, item


def _source_ids(item: dict, field: str) -> list[str]:
    values = item.get(field) or []
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _fact_fields(fact) -> list[str]:
    """The individual source fields of a fact, in citation order."""
    value_json = getattr(fact, "value_json", {}) or {}
    return [
        str(value_json.get("text") or ""),
        str(getattr(fact, "organization", "") or ""),
        str(getattr(fact, "role_title", "") or ""),
        str(getattr(fact, "start_date", "") or ""),
        str(getattr(fact, "end_date", "") or ""),
        str(getattr(fact, "source_text", "") or ""),
    ]


def _fact_corpus(fact) -> str:
    return " ".join(value for value in _fact_fields(fact) if value)


def _target_corpus(target) -> str:
    criteria = getattr(target, "acceptance_criteria_json", []) or []
    return " ".join(
        [
            str(getattr(target, "deliverable", "") or ""),
            *(str(value) for value in criteria),
        ]
    )
