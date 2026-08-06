"""小说管线数据模型。

一个「小说项目」对应一个共享工作区（workspace），所有子工作流都跑在
同一个工作区里，前一个工作流写出的文件就是下一个工作流的输入，
从而实现「完成上一个，自动进入下一个」，无需手动导入。
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

# 小说项目根目录（运行数据内，E 盘）
NOVEL_PROJECTS_DIR = DATA_DIR / "novel-projects"

# 完整文本的 E 盘存档根目录（可改，默认 E:\故事机器\小说存档）
NOVEL_ARCHIVE_DIR = Path(
    os.getenv("NOVEL_ARCHIVE_DIR", "E:/故事机器/小说存档")
).expanduser().resolve()

# 流水线固定顺序：先建世界 → 建角色 → 故事规划 → 卷纲近纲 → 逐章生产
PREP_WORKFLOWS: list[tuple[str, str, str]] = [
    ("build", "世界观构建", "bishu-novel-build"),
    ("character", "角色创建", "bishu-novel-character"),
    ("story-plan", "故事宏观规划", "bishu-novel-story-plan"),
    ("outline", "卷纲+近纲规划", "bishu-novel-outline"),
]

CHAPTER_WORKFLOWS: list[tuple[str, str, str]] = [
    ("mvp", "章节生产", "bishu-novel-mvp"),
    ("post-hoc", "章节后验", "bishu-novel-post-hoc"),
    ("polish", "章节润色", "bishu-novel-polish"),
]

TERMINAL_TASK_STATUSES = {"completed", "failed", "stopped", "cancelled"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe_filename(name: str) -> str:
    """把书名变成安全的文件夹名（保留中文，去掉非法字符）。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", str(name or "")).strip()
    return re.sub(r"\s+", " ", cleaned) or "未命名小说"


def zero_pad_chapter(chapter: Any) -> str:
    """章节号统一为 4 位数字，如 1 -> 0001。"""
    try:
        return f"{int(chapter):04d}"
    except (TypeError, ValueError):
        return "0001"


@dataclass
class PipelineStep:
    """流水线中的一个步骤 = 某一个子工作流的一次任务。"""
    key: str
    label: str
    workflow_id: str
    workflow_name: str = ""
    status: str = "pending"           # pending/running/completed/failed
    task_id: str = ""
    error: str = ""
    chapter_number: str = ""          # 章节步骤才有的编号（0001）
    started_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineStep":
        return cls(**{k: data.get(k, "") for k in cls.__dataclass_fields__})


@dataclass
class NovelProject:
    """一部小说的完整配置 + 流水线执行状态。"""
    project_id: str
    name: str
    premise: str = ""
    genre: str = ""
    language: str = "中文"
    chapters: list[int] = field(default_factory=lambda: [1, 2, 3])
    target_word_count: str = "3000-4000"
    estimated_length: str = "中"
    words_per_chapter: str = "2000-2500"
    human_intent: str = ""
    world_intent: str = ""
    writer_type: str = "single"
    world_id: str = ""                # 关联的剧场世界（建书时自动创建）
    character_ids: list[str] = field(default_factory=list)   # 关联人物库角色
    theater_session_ids: list[str] = field(default_factory=list)  # 关联剧场会话
    skill_ids: list[str] = field(default_factory=list)        # 挂载的写作风格 Skills
    extra_workflow_ids: list[str] = field(default_factory=list)  # 用户自定义加入的工作流
    assistant_enabled: bool = True                             # 总大脑 AI 开关
    assistant_model: str = ""                                  # 总大脑模型（空=默认 glm-4.6）
    archive_root: str = ""                                     # 存档根目录（空=默认 E:\故事机器\小说存档）
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    status: str = "idle"              # idle/running/completed/failed/stopped
    current_step: str = ""
    error: str = ""
    workspace: str = ""
    final_text_path: str = ""
    archive_path: str = ""
    steps: list[PipelineStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "premise": self.premise,
            "genre": self.genre,
            "language": self.language,
            "chapters": list(self.chapters),
            "target_word_count": self.target_word_count,
            "estimated_length": self.estimated_length,
            "words_per_chapter": self.words_per_chapter,
            "human_intent": self.human_intent,
            "world_intent": self.world_intent,
            "writer_type": self.writer_type,
            "world_id": self.world_id,
            "character_ids": list(self.character_ids),
            "theater_session_ids": list(self.theater_session_ids),
            "skill_ids": list(self.skill_ids),
            "extra_workflow_ids": list(self.extra_workflow_ids),
            "assistant_enabled": self.assistant_enabled,
            "assistant_model": self.assistant_model,
            "archive_root": self.archive_root,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "current_step": self.current_step,
            "error": self.error,
            "workspace": self.workspace,
            "final_text_path": self.final_text_path,
            "archive_path": self.archive_path,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NovelProject":
        chapters = data.get("chapters", [])
        if isinstance(chapters, str):
            try:
                chapters = json.loads(chapters)
            except (json.JSONDecodeError, TypeError):
                chapters = [1, 2, 3]
        if not isinstance(chapters, list):
            chapters = [1, 2, 3]
        chapters = [int(c) for c in chapters if str(c).strip().isdigit()] or [1, 2, 3]
        steps = [PipelineStep.from_dict(s) for s in data.get("steps", [])]
        return cls(
            project_id=data.get("project_id", ""),
            name=data.get("name", ""),
            premise=data.get("premise", ""),
            genre=data.get("genre", ""),
            language=data.get("language", "中文") or "中文",
            chapters=chapters,
            target_word_count=data.get("target_word_count", "3000-4000"),
            estimated_length=data.get("estimated_length", "中") or "中",
            words_per_chapter=data.get("words_per_chapter", "2000-2500"),
            human_intent=data.get("human_intent", ""),
            world_intent=data.get("world_intent", ""),
            writer_type=data.get("writer_type", "single") or "single",
            world_id=data.get("world_id", "") or "",
            character_ids=[
                str(c) for c in (data.get("character_ids") or []) if str(c).strip()
            ],
            theater_session_ids=[
                str(s) for s in (data.get("theater_session_ids") or []) if str(s).strip()
            ],
            skill_ids=[
                str(s) for s in (data.get("skill_ids") or []) if str(s).strip()
            ],
            extra_workflow_ids=[
                str(w) for w in (data.get("extra_workflow_ids") or []) if str(w).strip()
            ],
            assistant_enabled=bool(data.get("assistant_enabled", True)),
            assistant_model=data.get("assistant_model", "") or "",
            archive_root=data.get("archive_root", "") or "",
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
            status=data.get("status", "idle") or "idle",
            current_step=data.get("current_step", ""),
            error=data.get("error", ""),
            workspace=data.get("workspace", ""),
            final_text_path=data.get("final_text_path", ""),
            archive_path=data.get("archive_path", ""),
            steps=steps,
        )

    def build_steps(self) -> list[PipelineStep]:
        """按流水线顺序重建全部步骤（含逐章循环）。"""
        steps: list[PipelineStep] = []
        for key, label, wf_id in PREP_WORKFLOWS:
            steps.append(PipelineStep(
                key=key, label=label, workflow_id=wf_id,
                workflow_name=wf_id,
            ))
        # 用户自定义工作流（加在准备阶段之后、章节循环之前）
        from src.config import WORKFLOWS_DIR
        import json as _json
        for wf_id in self.extra_workflow_ids:
            label = wf_id
            def_file = WORKFLOWS_DIR / wf_id / "definition.json"
            if def_file.exists():
                try:
                    label = _json.loads(def_file.read_text(encoding="utf-8")).get("name") or wf_id
                except Exception:
                    pass
            steps.append(PipelineStep(
                key=f"extra-{wf_id}",
                label=f"自定义 · {label}",
                workflow_id=wf_id,
                workflow_name=label,
            ))
        for ch in self.chapters:
            ch_num = zero_pad_chapter(ch)
            for suffix, label, wf_id in CHAPTER_WORKFLOWS:
                steps.append(PipelineStep(
                    key=f"chapter-{ch_num}-{suffix}",
                    label=f"第{int(ch)}章 · {label}",
                    workflow_id=wf_id,
                    workflow_name=wf_id,
                    chapter_number=ch_num,
                ))
        return steps

    def step_params(self, step: PipelineStep) -> dict[str, str]:
        """按步骤类型生成传给子工作流任务的参数。"""
        common = {"language": self.language or "中文"}
        if step.key == "build":
            return {**common, "premise": self.premise, "genre": self.genre}
        if step.key == "character":
            return {**common, "premise": self.premise, "genre": self.genre}
        if step.key == "story-plan":
            return {**common, "premise": self.premise, "genre": self.genre}
        if step.key == "outline":
            return {
                **common,
                "volume_number": "1",
                "estimated_length": self.estimated_length,
                "words_per_chapter": self.words_per_chapter,
                "latest_chapter": "0000",
            }
        if step.key.endswith("-mvp"):
            prev_ch = max(0, int(step.chapter_number or 1) - 1)
            return {
                **common,
                "chapter_number": zero_pad_chapter(step.chapter_number or 1),
                "prev_chapter": zero_pad_chapter(prev_ch),
                "human_intent": self.human_intent,
                "world_intent": self.world_intent,
                "target_word_count": self.target_word_count,
                "writer_type": self.writer_type,
            }
        if step.key.endswith("-post-hoc") or step.key.endswith("-polish"):
            return {
                **common,
                "chapter_number": zero_pad_chapter(step.chapter_number or 1),
            }
        if step.key.startswith("extra-"):
            return common
        return common


def ensure_dirs() -> None:
    NOVEL_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    NOVEL_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def project_path(project_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", project_id)
    if not safe:
        raise ValueError("project_id 非法")
    return NOVEL_PROJECTS_DIR / safe / "project.json"


def workspace_path(project_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", project_id)
    if not safe:
        raise ValueError("project_id 非法")
    return NOVEL_PROJECTS_DIR / safe / "workspace"


def load_project(project_id: str) -> NovelProject | None:
    path = project_path(project_id)
    if not path.exists():
        return None
    try:
        return NovelProject.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        logger.exception("加载小说项目失败: %s", project_id)
        return None


def save_project(project: NovelProject) -> None:
    project.updated_at = _now_iso()
    path = project_path(project.project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(project.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def list_projects() -> list[NovelProject]:
    ensure_dirs()
    projects: list[NovelProject] = []
    if not NOVEL_PROJECTS_DIR.exists():
        return projects
    for item in sorted(NOVEL_PROJECTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not item.is_dir():
            continue
        proj = load_project(item.name)
        if proj is not None:
            projects.append(proj)
    return projects
