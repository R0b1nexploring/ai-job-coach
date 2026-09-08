"""Versioned in-app template. No template catalog table in this release."""

from copy import deepcopy

TEMPLATE_ID = "classic-navy-ats-v2"
BLUEPRINT_FOOTER = "* 为目标蓝图内容，尚未形成可核验经历"
BLUEPRINT_MARK = "*"

CLASSIC_NAVY_ATS_V2 = {
    "id": TEMPLATE_ID,
    "version": "2",
    "description": "中文理工科单页 ATS 模板",
    "page": {
        "width_mm": 210,
        "height_mm": 297,
        "margin_horizontal_mm": 16,
        "margin_vertical_mm": 18,
        "max_pages": 1,
    },
    "typography": {
        "cjk_font": "微软雅黑",
        "heading_cjk_font": "黑体",
        "latin_font": "Calibri",
        "name_size_pt": 22,
        "section_size_pt": 12,
        "body_size_pt": 10.5,
        "line_spacing": 1.15,
        "line_spacing_min": 1.0,
    },
    "colors": {
        "ink": "1F2933",
        "accent": "2F3E63",
        "muted": "5B6575",
        "border": "2F3E63",
        "background": "ECEBE6",
    },
    "layout": {
        "section_order": [
            "求职方向",
            "教育背景",
            "实习/工作",
            "项目/科研/竞赛",
            "奖项证书",
            "技能",
        ],
        "hide_empty_sections": True,
        "portrait_optional": True,
        "blueprint_mark": BLUEPRINT_MARK,
        "blueprint_footer": BLUEPRINT_FOOTER,
    },
}

CATEGORY_SECTIONS = {
    "education": "教育背景",
    "employment": "实习/工作",
    "projects": "项目/科研/竞赛",
    "certificates": "奖项证书",
    "skills": "技能",
    "other": "项目/科研/竞赛",
}
SECTION_ORDER = [
    "教育背景",
    "实习/工作",
    "项目/科研/竞赛",
    "奖项证书",
    "技能",
]


def template_snapshot(overrides: dict | None = None) -> dict:
    snapshot = deepcopy(CLASSIC_NAVY_ATS_V2)
    if overrides:
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(snapshot.get(key), dict):
                snapshot[key] = {**snapshot[key], **value}
            else:
                snapshot[key] = value
    return snapshot


def assert_snapshot_has_no_pii(snapshot: dict) -> None:
    encoded = str(snapshot)
    forbidden = ("姓名", "电话", "邮箱", "@", "resume_self")
    for token in forbidden:
        if token in encoded and token in {"resume_self"}:
            raise ValueError("template snapshot must not include private resume paths")
