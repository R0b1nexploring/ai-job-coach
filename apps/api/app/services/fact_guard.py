import re


ENTITY_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?|CAD|SolidWorks|PLC|六西格玛|证书", re.I)


def guard_content(content: dict, confirmed_facts: list) -> tuple[str, list[str]]:
    allowed = " ".join(str(f.value_json) for f in confirmed_facts)
    allowed_ids = {str(f.id) for f in confirmed_facts if getattr(f, "id", None)}
    new_claims = []
    for section in content.get("sections", []):
        for item in section.get("items", []):
            source_ids = {str(value) for value in item.get("source_fact_ids", [])}
            if not source_ids:
                new_claims.append("缺少事实来源")
            elif not source_ids.issubset(allowed_ids):
                new_claims.append("引用了未确认或不属于当前用户的事实")
            for entity in ENTITY_PATTERN.findall(item.get("text", "")):
                if entity.lower() not in allowed.lower():
                    new_claims.append(entity)
            new_claims.extend(item.get("new_claims", []))
    return ("blocked" if new_claims else "passed", sorted(set(new_claims)))
