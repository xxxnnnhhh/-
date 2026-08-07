"""流水线预检：把书设定落到正确路径，按步骤检测前置文件是否就位，再决定能否运行。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import NovelProject, PipelineStep

logger = logging.getLogger(__name__)

# 各步骤所需的前置文件（相对工作区）；extra-* 未知需求视为就绪
STEP_REQUIREMENTS: dict[str, list[str]] = {
    "build": [],
    "character": ["meta/world_foundation.md"],
    "story-plan": ["meta/world_foundation.md", "meta/character_profiles.md"],
    "outline": [
        "meta/world_foundation.md",
        "meta/character_profiles.md",
        "meta/story_plan.md",
    ],
    "mvp": [
        "meta/world_foundation.md",
        "meta/character_profiles.md",
        "meta/character_voice.md",
        "meta/style_profile.md",
        "meta/story_plan.md",
        "outline/volume_outline.md",
        "outline/near_term_outline.md",
    ],
    "post-hoc": ["story/{ch}/chapter.md"],
    "polish": ["story/{ch}/chapter.md"],
}


def _requirements(step: "PipelineStep") -> list[str]:
    key = step.key
    if key.startswith("extra-"):
        return []
    kind = None
    for suffix, reqs in STEP_REQUIREMENTS.items():
        if key == suffix or key.endswith("-" + suffix) or key.endswith(suffix):
            kind = suffix
            reqs_used = reqs
            break
    if kind is None:
        return []
    return [r.replace("{ch}", step.chapter_number or "0001") for r in reqs_used]


def materialize_inputs(project: "NovelProject") -> dict:
    """把书设定写入工作区正确路径，供各工作流文件变量读取。"""
    ws = Path(project.workspace)
    ws.mkdir(parents=True, exist_ok=True)
    meta = ws / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    files = {
        "meta/book_rules.md": project.rules,
        "meta/premise.md": project.premise,
        "meta/genre.md": project.genre,
        "meta/language.md": project.language,
        "meta/human_intent.md": project.human_intent,
        "meta/world_intent.md": project.world_intent,
    }
    for rel, content in files.items():
        p = ws / rel
        text = (content or "").strip()
        if text:
            p.write_text(text + "\n", encoding="utf-8")
            written.append(rel)

    # 全书配置（供脚本/总大脑读取）
    cfg_path = meta / "book_config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "name": project.name,
                "premise": project.premise,
                "genre": project.genre,
                "language": project.language,
                "rules": project.rules,
                "human_intent": project.human_intent,
                "world_intent": project.world_intent,
                "writer_type": project.writer_type,
                "chapters": project.chapters,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    written.append("meta/book_config.json")
    return {"written": written, "count": len(written)}


def precheck(project: "NovelProject") -> dict:
    """预检：按顺序检测每步前置文件，返回报告（不执行）。

    顺序流水线里，后一步的文件本来就由前一步生成——所以只有"第一个未完成步骤"
    真正决定能否继续：它的前置齐了就绪，缺了就阻塞；更后面的步骤一律显示
    "待前序"（由前面的步骤自动生成），不再当错误一屏列红。
    """
    materialize_inputs(project)
    ws = Path(project.workspace)
    report: list[dict] = []
    blocking: list[str] = []
    next_step: dict | None = None
    first_incomplete_seen = False
    for step in project.steps:
        reqs = _requirements(step)
        missing = [
            r for r in reqs
            if not (ws / r).is_file()
        ]
        if step.status == "completed":
            report.append({
                "key": step.key,
                "label": step.label,
                "status": "已运行",
                "missing": [],
            })
            continue
        if not first_incomplete_seen:
            first_incomplete_seen = True
            next_step = {"key": step.key, "label": step.label}
            if missing:
                blocking = missing
                status = "缺前置"
            else:
                status = "就绪"
        else:
            # 后续步骤：缺的文件由前面的步骤生成，属等待，不算错误
            status = "待前序"
            missing = []
        report.append({
            "key": step.key,
            "label": step.label,
            "status": status,
            "missing": [],
        })
    ok = not blocking
    if ok and next_step is not None:
        message = f"前置就绪，下一步：{next_step['label']} —— 可直接「继续连跑」"
    elif ok:
        message = "所有步骤已完成"
    else:
        message = (
            f"卡在「{next_step['label']}」：缺 {', '.join(blocking)}"
            " —— 先完成该步骤（或从它开始跑）"
        )
    return {
        "ok": ok,
        "blocking": blocking,
        "next_step": next_step,
        "steps": report,
        "message": message,
    }
