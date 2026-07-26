import re

_METRIC_PATTERN = re.compile(r"\d+(?:\.\d+)?(?:%|％|万|千|百|倍|人|月|年|天|个|项|次|台|套)")
_STRONG_VERB_PATTERN = re.compile(
    r"^(?:主导|统筹|牵头|搭建|开发|实现|完成|落地|优化|重构|改进|升级|迭代|"
    r"协调|推动|对接|联动|协同|达成|突破|创造|实现|"
    r"分析|诊断|评估|调研|洞察|策划|设计|构思|提出|创新|"
    r"管理|运营|维护|监控|保障|带领|规划)"
)
_WEAK_VERB_PATTERN = re.compile(r"^(?:负责|参与|协助)")

_REQUIRED_SECTIONS = {"工作经历", "项目经验", "技能证书", "教育背景"}


def score_resume(content: dict, job: dict) -> dict:
    sections = content.get("sections", [])
    all_items = [item for section in sections for item in section.get("items", [])]
    section_names = {section.get("name", "") for section in sections}

    dimensions = []
    suggestions = []

    keyword_score = _score_keyword_match(all_items, job)
    dimensions.append({"name": "岗位匹配度", "score": keyword_score, "weight": 30})
    if keyword_score < 60:
        suggestions.append("JD 关键词覆盖率偏低，建议在经历描述中融入更多岗位要求的核心技能")

    content_score = _score_content_quality(all_items)
    dimensions.append({"name": "内容质量", "score": content_score, "weight": 25})
    if content_score < 60:
        suggestions.append("建议使用 STAR 法则（背景→任务→行动→结果）重写经历，用强动词替代「负责/参与」")

    structure_score = _score_structure(section_names)
    dimensions.append({"name": "结构完整性", "score": structure_score, "weight": 20})
    missing = _REQUIRED_SECTIONS - section_names
    if missing:
        suggestions.append(f"缺少标准模块：{'、'.join(sorted(missing))}")

    relevance_score = _score_relevance(all_items, job)
    dimensions.append({"name": "经历相关性", "score": relevance_score, "weight": 15})
    if relevance_score < 60:
        suggestions.append("经历与目标岗位关联度不高，建议按 JD 相关性重新排列经历优先级")

    metric_score = _score_metrics(all_items)
    dimensions.append({"name": "量化程度", "score": metric_score, "weight": 10})
    if metric_score < 60:
        suggestions.append("量化数据不足，建议为每段经历补充至少 1 个数据指标（如提升比例、处理数量）")

    total_weight = sum(d["weight"] for d in dimensions)
    overall = round(sum(d["score"] * d["weight"] for d in dimensions) / total_weight) if total_weight else 0

    if not suggestions:
        suggestions.append("简历整体质量良好，建议针对不同岗位继续微调关键词覆盖")

    return {
        "score": overall,
        "dimensions": dimensions,
        "suggestions": suggestions,
    }


def _score_keyword_match(items: list[dict], job: dict) -> int:
    keywords = job.get("keywords", []) + job.get("must_have", [])
    if not keywords:
        return 70
    all_text = " ".join(item.get("text", "") for item in items).lower()
    hits = sum(1 for kw in keywords if kw.lower() in all_text)
    ratio = hits / len(keywords)
    return min(100, round(ratio * 120))


def _score_content_quality(items: list[dict]) -> int:
    if not items:
        return 40
    strong = 0
    weak = 0
    for item in items:
        text = item.get("text", "")
        if _STRONG_VERB_PATTERN.match(text):
            strong += 1
        elif _WEAK_VERB_PATTERN.match(text):
            weak += 1
    total = len(items)
    strong_ratio = strong / total if total else 0
    weak_ratio = weak / total if total else 0
    score = 50 + round(strong_ratio * 40) - round(weak_ratio * 20)
    return max(0, min(100, score))


def _score_structure(section_names: set[str]) -> int:
    present = len(_REQUIRED_SECTIONS & section_names)
    return round(present / len(_REQUIRED_SECTIONS) * 100)


def _score_relevance(items: list[dict], job: dict) -> int:
    keywords = job.get("keywords", []) + job.get("must_have", []) + job.get("responsibilities", [])
    if not keywords or not items:
        return 50
    experience_items = [
        item for item in items
        if any(name in item.get("text", "") for name in ("负责", "主导", "开发", "设计", "运营", "维护"))
    ]
    target = experience_items or items
    all_text = " ".join(item.get("text", "") for item in target).lower()
    hits = sum(1 for kw in keywords if kw.lower() in all_text)
    ratio = hits / len(keywords)
    return min(100, round(ratio * 110))


def _score_metrics(items: list[dict]) -> int:
    if not items:
        return 30
    with_metrics = sum(1 for item in items if _METRIC_PATTERN.search(item.get("text", "")))
    ratio = with_metrics / len(items)
    return min(100, round(ratio * 130))
