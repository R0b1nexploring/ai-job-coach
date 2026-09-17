#!/usr/bin/env python3
"""Author 20 fictional job-seeking resumes locally (no external model calls).

Five directions: mechanical, computer, AI, electronics, electrical.  Every
sample is assembled through the real ``assemble_model_copy`` / ``validate_content``
contract and checked by the deterministic quality gate, then rendered to HTML
and DOCX.  All names, schools and companies are fictional; artifacts stay in
gitignored ``tmp/generated/``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("RESUME_QUALITY_GATE_ENABLED", "true")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.copy_assembler import assemble_model_copy
from app.services.docx_resume_renderer import render_resume_docx
from app.services.html_resume_renderer import render_resume_html
from app.services.quality_service import evaluate_version

CONTACT = {"name": "虚构样本", "email": "fictional@example.test", "city": "虚构城市"}

DIRECTIONS: dict[str, dict] = {
    "mechanical": {
        "title": "机械设计助理工程师",
        "university": "虚构理工大学",
        "major": "机械设计制造及其自动化",
        "start": "2022-09",
        "end": "2026-07",
        "skills": ["SolidWorks", "AutoCAD", "机械制图", "工程图标注", "GD&T 基础"],
        "projects": [
            {
                "id": "reducer",
                "org": "虚构理工大学",
                "role": "项目成员",
                "start": "2025-03",
                "end": "2025-06",
                "bullets": [
                    "使用 SolidWorks 参数化完成二级减速器箱体与齿轮轴建模",
                    "通过装配干涉检查调整轴承座位置，消除箱体与轴系干涉",
                    "输出减速器装配图与关键零件图，标注配合与尺寸公差",
                ],
            },
            {
                "id": "fixture",
                "org": "虚构理工大学",
                "role": "课程学生",
                "start": "2024-09",
                "end": "2024-12",
                "bullets": [
                    "设计钻孔夹具的定位与夹紧方案，绘制装配工程图",
                    "按六点定位原理选择定位元件并校核夹紧力方向",
                    "整理设计说明与图纸检查记录，支持课程验收",
                ],
            },
            {
                "id": "verify-record",
                "org": "虚构精工实习岗",
                "role": "技术实习生",
                "start": "2025-07",
                "end": "2025-09",
                "bullets": [
                    "为减速器关键配合尺寸建立设计验证检查项与判定标准",
                    "对比两种轴承座结构方案，记录刚度与装配性取舍",
                    "输出验证记录表，逐项对应图纸尺寸与检查结果",
                ],
            },
        ],
    },
    "computer": {
        "title": "后端开发实习生",
        "university": "虚构理工大学",
        "major": "计算机科学与技术",
        "start": "2022-09",
        "end": "2026-07",
        "skills": ["Java", "Spring Boot", "MySQL", "Git", "JUnit"],
        "projects": [
            {
                "id": "lost-found",
                "org": "虚构理工大学",
                "role": "后端负责人",
                "start": "2025-02",
                "end": "2025-05",
                "bullets": [
                    "使用 Spring Boot 实现失物登记、查询与认领 REST 接口",
                    "设计 MySQL 失物与用户表结构并编写联合查询",
                    "接入 JWT 鉴权并补充接口单元测试",
                ],
            },
            {
                "id": "library-db",
                "org": "虚构理工大学",
                "role": "课程学生",
                "start": "2024-09",
                "end": "2024-12",
                "bullets": [
                    "设计图书借阅数据库的实体关系与第三范式表结构",
                    "编写借阅统计视图与存储过程，减少重复查询",
                    "用索引优化高频查询并对比执行计划",
                ],
            },
            {
                "id": "cache-perf",
                "org": "虚构网络科技实习岗",
                "role": "开发实习生",
                "start": "2025-07",
                "end": "2025-09",
                "bullets": [
                    "为热点查询接口引入本地缓存并设置过期策略",
                    "使用压测脚本对比优化前后的响应时间",
                    "整理接口文档与异常返回约定",
                ],
            },
        ],
    },
    "ai": {
        "title": "算法实习生",
        "university": "虚构理工大学",
        "major": "人工智能",
        "start": "2022-09",
        "end": "2026-07",
        "skills": ["Python", "PyTorch", "pandas", "NumPy", "scikit-learn"],
        "projects": [
            {
                "id": "image-cls",
                "org": "虚构理工大学",
                "role": "模型训练成员",
                "start": "2025-03",
                "end": "2025-06",
                "bullets": [
                    "使用 PyTorch 搭建卷积网络完成图像分类训练",
                    "通过数据增强与学习率调整提升验证集表现",
                    "记录训练曲线与混淆矩阵，分析误分类样本",
                ],
            },
            {
                "id": "data-clean",
                "org": "虚构理工大学",
                "role": "课程学生",
                "start": "2024-10",
                "end": "2024-12",
                "bullets": [
                    "使用 pandas 清洗传感器采样数据并处理缺失值",
                    "编写异常值检测规则并输出异常记录表",
                    "将清洗流程封装为可重复执行的脚本",
                ],
            },
            {
                "id": "text-cls",
                "org": "虚构智能科技实习岗",
                "role": "算法实习生",
                "start": "2025-07",
                "end": "2025-09",
                "bullets": [
                    "使用朴素贝叶斯与词袋特征完成文本分类基线",
                    "对比不同特征处理对准确率的影响",
                    "整理实验记录与错误分析",
                ],
            },
        ],
    },
    "electronics": {
        "title": "硬件设计实习生",
        "university": "虚构理工大学",
        "major": "电子信息工程",
        "start": "2022-09",
        "end": "2026-07",
        "skills": ["STM32", "C", "Altium Designer", "示波器", "电路调试"],
        "projects": [
            {
                "id": "thermostat",
                "org": "虚构理工大学",
                "role": "嵌入式负责人",
                "start": "2025-03",
                "end": "2025-06",
                "bullets": [
                    "使用 STM32 采集温度传感器数据并实现闭环控制",
                    "编写 C 语言驱动与定时中断，完成 PWM 输出",
                    "记录调试数据并分析超调与稳态误差",
                ],
            },
            {
                "id": "pcb-power",
                "org": "虚构理工大学",
                "role": "课程学生",
                "start": "2024-09",
                "end": "2024-12",
                "bullets": [
                    "使用 Altium Designer 设计电源模块原理图与双层 PCB",
                    "完成器件布局与走线，检查电源与地平面完整性",
                    "整理设计文件与电气规则检查结果",
                ],
            },
            {
                "id": "signal",
                "org": "虚构电子科技实习岗",
                "role": "硬件实习生",
                "start": "2025-07",
                "end": "2025-09",
                "bullets": [
                    "设计分压与滤波电路调理传感器输出信号",
                    "用示波器测量纹波并调整滤波参数",
                    "记录测试数据与改进过程",
                ],
            },
        ],
    },
    "electrical": {
        "title": "电气自动化助理工程师",
        "university": "虚构理工大学",
        "major": "电气工程及其自动化",
        "start": "2022-09",
        "end": "2026-07",
        "skills": ["PLC", "变频器", "电气图纸", "Eplan 基础", "万用表"],
        "projects": [
            {
                "id": "motor-control",
                "org": "虚构理工大学",
                "role": "项目成员",
                "start": "2025-02",
                "end": "2025-05",
                "bullets": [
                    "使用 PLC 编写电机启停与调速控制逻辑",
                    "配置变频器参数并完成联调",
                    "记录联调过程与故障排查步骤",
                ],
            },
            {
                "id": "switchgear",
                "org": "虚构职业技术学院",
                "role": "实训学生",
                "start": "2024-07",
                "end": "2024-08",
                "bullets": [
                    "按电气原理图完成配电柜元器件接线",
                    "执行通电前检查并排除一处接线错误",
                    "整理实训验收记录与安全操作要点",
                ],
            },
            {
                "id": "drawing",
                "org": "虚构电气设备实习岗",
                "role": "电气实习生",
                "start": "2025-07",
                "end": "2025-09",
                "bullets": [
                    "绘制电机正反转控制原理图与接线图",
                    "标注元件符号与端子编号，核对图纸一致性",
                    "整理图纸清单与元件明细表",
                ],
            },
        ],
    },
}


def _facts_for(project: dict, direction: str) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=f"f-{direction}-{project['id']}-{index}",
            category="projects",
            label=project["id"],
            organization=project["org"],
            role_title=project["role"],
            location="虚构城市",
            start_date=project["start"],
            end_date=project["end"],
            value_json={"text": text},
            source_text=text,
            verification_status="user_confirmed",
            material_id=f"m-{direction}-{project['id']}",
            claim_type="action",
            evidence_json={"artifact": f"{project['id']} 过程记录"},
        )
        for index, text in enumerate(project["bullets"])
    ]


def _build(direction: str, cfg: dict, projects: list[dict]) -> tuple[dict, list[SimpleNamespace]]:
    facts: list[SimpleNamespace] = []
    sections: list[dict] = []

    edu_fact = SimpleNamespace(
        id=f"f-{direction}-education",
        category="education",
        label=cfg["major"],
        organization=cfg["university"],
        role_title="本科",
        location="虚构城市",
        start_date=cfg["start"],
        end_date=cfg["end"],
        value_json={"text": f"{cfg['university']} {cfg['major']} 本科，预计 {cfg['end']} 毕业"},
        source_text="",
        verification_status="user_confirmed",
        material_id=f"m-{direction}-education",
        claim_type="education",
        evidence_json={},
    )
    facts.append(edu_fact)
    sections.append({
        "name": "教育背景",
        "presentation": "items",
        "items": [{
            "organization": cfg["university"],
            "role_title": "本科",
            "location": "虚构城市",
            "start_date": cfg["start"],
            "end_date": cfg["end"],
            "bullets": [{
                "text": f"{cfg['major']}本科，主修课程覆盖{cfg['skills'][0]}等方向",
                "source_fact_ids": [edu_fact.id],
                "requirement_ids": [],
                "source_target_ids": [],
                "achieved": True,
            }],
        }],
    })

    items = []
    for project in projects:
        project_facts = _facts_for(project, direction)
        facts.extend(project_facts)
        items.append({
            "organization": project["org"],
            "role_title": project["role"],
            "location": "虚构城市",
            "start_date": project["start"],
            "end_date": project["end"],
            "bullets": [
                {
                    "text": text,
                    "source_fact_ids": [fact.id],
                    "requirement_ids": [],
                    "source_target_ids": [],
                    "achieved": True,
                }
                for text, fact in zip(project["bullets"], project_facts, strict=True)
            ],
        })
    sections.append({"name": "项目/科研/竞赛", "presentation": "items", "items": items})

    skill_facts = [
        SimpleNamespace(
            id=f"f-{direction}-skill-{index}",
            category="skills",
            label=skill,
            organization="",
            role_title="",
            location="",
            start_date="",
            end_date="",
            value_json={"text": skill},
            source_text=skill,
            verification_status="user_confirmed",
            material_id=f"m-{direction}-skill-{index}",
            claim_type="skill",
            evidence_json={},
        )
        for index, skill in enumerate(cfg["skills"])
    ]
    facts.extend(skill_facts)
    sections.append({
        "name": "技能",
        "presentation": "tags",
        "items": [{
            "organization": "",
            "role_title": "",
            "location": "",
            "start_date": "",
            "end_date": "",
            "bullets": [
                {
                    "text": skill,
                    "source_fact_ids": [fact.id],
                    "requirement_ids": [],
                    "source_target_ids": [],
                    "achieved": True,
                }
                for skill, fact in zip(cfg["skills"], skill_facts, strict=True)
            ],
        }],
    })

    content = assemble_model_copy(
        {"headline": cfg["title"], "sections": sections},
        facts=facts,
        requirements=[],
        kind="submittable",
        headline=cfg["title"],
        contact=CONTACT,
    )
    return content, facts


def _samples() -> list[tuple[str, list[dict]]]:
    combos = [(0, 1), (1, 2), (0, 2), (0, 1, 2)]
    out = []
    for direction, cfg in DIRECTIONS.items():
        projects = cfg["projects"]
        for combo in combos:
            out.append((direction, [projects[index] for index in combo]))
    return out


def main() -> int:
    out_dir = ROOT / "tmp" / "generated" / "resume-samples-authored"
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for number, (direction, projects) in enumerate(_samples()):
        cfg = DIRECTIONS[direction]
        content, facts = _build(direction, cfg, projects)
        report = evaluate_version(content=content, facts=facts, requirements=[], mode="submittable")
        folder = out_dir / f"sample-{number:02d}-{direction}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "resume.json").write_text(
            json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (folder / "resume.html").write_text(
            render_resume_html(content, cfg["title"]), encoding="utf-8"
        )
        (folder / "resume.docx").write_bytes(render_resume_docx(content, cfg["title"]))
        row = {
            "index": number,
            "direction": direction,
            "headline": cfg["title"],
            "projects": [project["id"] for project in projects],
            "hard_passed": report["hard_passed"],
            "issues": report["issues"],
            "bullets": sum(
                len(item.get("bullets") or [])
                for section in content["sections"]
                for item in section.get("items") or []
            ),
        }
        index.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    (out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    passed = sum(1 for row in index if row["hard_passed"])
    print(f"AUTHORED {len(index)} samples, hard_passed={passed}, out={out_dir.relative_to(ROOT)}")
    return 0 if passed == len(index) else 1


if __name__ == "__main__":
    raise SystemExit(main())
