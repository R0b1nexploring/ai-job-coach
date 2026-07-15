import html
import re


def plain_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    value = re.sub(r"</(p|li|div|h[1-6])>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def relevance(
    title: str, body: str, keywords: list[str], cities: list[str], city: str
) -> list[str]:
    haystack = f"{title} {body}".lower()
    hits = [keyword for keyword in keywords if keyword.lower() in haystack]
    return list(dict.fromkeys(hits))
