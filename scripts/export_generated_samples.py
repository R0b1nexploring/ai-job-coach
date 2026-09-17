#!/usr/bin/env python3
"""Export locally generated fictional resumes into the web app's static data.

Sources:
- ``tmp/generated/resume-samples-authored/``  local-authored resumes
- ``tmp/generated/resume-samples-*/``         real-Provider pipeline samples

Writes ``apps/web/public/generated-samples/index.json`` plus one content file
per sample, and copies rendered HTML/DOCX when available.  Only fictional data
is exported.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps" / "web" / "public" / "generated-samples"
AUTHORED = ROOT / "tmp" / "generated" / "resume-samples-authored"

DIRECTION_LABELS = {
    "mechanical": "机械",
    "computer": "计算机",
    "ai": "AI",
    "electronics": "电子",
    "electrical": "电气",
}


def _project_rows(content: dict) -> list[dict]:
    rows = []
    for section in content.get("sections") or []:
        for item in section.get("items") or []:
            bullets = [str(b.get("text") or "") for b in item.get("bullets") or []]
            if not bullets:
                continue
            rows.append({
                "organization": str(item.get("organization") or ""),
                "role_title": str(item.get("role_title") or ""),
                "section": str(section.get("name") or ""),
                "bullets": bullets,
            })
    return rows


def _bullet_count(content: dict) -> int:
    return sum(len(row["bullets"]) for row in _project_rows(content))


def export_authored() -> list[dict]:
    items = []
    if not AUTHORED.exists():
        return items
    for folder in sorted(AUTHORED.glob("sample-*")):
        resume = folder / "resume.json"
        if not resume.exists():
            continue
        content = json.loads(resume.read_text(encoding="utf-8"))
        direction = folder.name.split("-")[-1]
        sample_id = f"authored-{folder.name.split('-')[1]}-{direction}"
        files = {"json": f"/generated-samples/{sample_id}.json"}
        for suffix in ("html", "docx"):
            source = folder / f"resume.{suffix}"
            if source.exists():
                shutil.copyfile(source, PUBLIC / f"{sample_id}.{suffix}")
                files[suffix] = f"/generated-samples/{sample_id}.{suffix}"
        (PUBLIC / f"{sample_id}.json").write_text(
            json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        items.append({
            "id": sample_id,
            "direction": direction,
            "direction_label": DIRECTION_LABELS.get(direction, direction),
            "title": str(content.get("headline") or ""),
            "bullet_count": _bullet_count(content),
            "projects": _project_rows(content),
            "files": files,
        })
    return items


def export_model() -> list[dict]:
    items = []
    for folder in sorted((ROOT / "tmp" / "generated").glob("resume-samples-*")):
        if folder.name == "resume-samples-authored":
            continue
        for sample in sorted(folder.glob("sample-*.json")):
            record = json.loads(sample.read_text(encoding="utf-8"))
            content = (record.get("content") or {}).get("submittable")
            if not content:
                continue
            direction = str(record.get("direction") or "unknown")
            sample_id = f"model-{folder.name.split('-')[-1]}-{sample.stem}-{direction}"
            (PUBLIC / f"{sample_id}.json").write_text(
                json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            items.append({
                "id": sample_id,
                "direction": direction,
                "direction_label": DIRECTION_LABELS.get(direction, direction),
                "title": str(content.get("headline") or ""),
                "bullet_count": _bullet_count(content),
                "projects": _project_rows(content),
                "writer_source": (record.get("writer_source") or {}).get("submittable"),
                "bundle_status": record.get("bundle_status"),
                "files": {"json": f"/generated-samples/{sample_id}.json"},
            })
    return items


def main() -> int:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    authored = export_authored()
    model = export_model()
    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "groups": [
            {
                "source": "model",
                "label": "真实模型样本",
                "note": "经真实 Provider 的 v3 管线生成，含本地回退样本",
                "items": model,
            },
            {
                "source": "authored",
                "label": "本地作者样本",
                "note": "由本机按内容合同撰写并渲染，用于积累虚构语料",
                "items": authored,
            },
        ],
    }
    (PUBLIC / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "model": len(model),
        "authored": len(authored),
        "out": str(PUBLIC.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
