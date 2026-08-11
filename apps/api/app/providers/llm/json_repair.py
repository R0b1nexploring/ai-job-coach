import json


def loads_lenient(text: str) -> dict:
    """Parse a JSON object while tolerating common Markdown and prose wrappers."""
    if not isinstance(text, str):
        raise TypeError("LLM 响应不是文本")

    raw = text.strip()
    candidates = [raw]
    if raw.startswith("```") and raw.endswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3:
            candidates.append("\n".join(lines[1:-1]).strip())

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            value = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("LLM 响应不包含有效 JSON 对象")
