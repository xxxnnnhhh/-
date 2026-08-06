"""小说管线 REST API。"""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .models import (
    NOVEL_ARCHIVE_DIR,
    NovelProject,
    ensure_dirs,
    list_projects,
    load_project,
    save_project,
    workspace_path,
)
from .runner import NovelPipelineRunner
from ..theater.models import World, TheaterSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/novel/pipelines", tags=["novel-pipeline"])


def _get_runner(request: Request) -> NovelPipelineRunner:
    return request.app.state.novel_pipeline_runner


class CreateProjectRequest(BaseModel):
    name: str = Field(description="书名")
    premise: str = Field(default="", description="故事创意/前提")
    genre: str = Field(default="", description="类型，如：东方玄幻、都市异能")
    language: str = Field(default="中文")
    chapters: list[int] = Field(default_factory=lambda: [1, 2, 3], description="章节号列表")
    target_word_count: str = Field(default="3000-4000", description="每章目标字数")
    estimated_length: str = Field(default="中", description="预计篇幅：短/中/长")
    words_per_chapter: str = Field(default="2000-2500", description="每章预计字数")
    human_intent: str = Field(default="", description="每章人类意图（剧情走向）")
    world_intent: str = Field(default="", description="每章世界意图（世界级推力）")
    writer_type: str = Field(default="single", description="写手模式 single/multi")


class RunRequest(BaseModel):
    reset: bool = Field(default=False, description="True=清空步骤从零重跑；False=从失败处继续")


class RunStepRequest(BaseModel):
    step_key: str = Field(description="要单独运行的步骤 key，如 build / outline / chapter-0001-mvp")


class AddCharacterRequest(BaseModel):
    character_id: str = Field(description="人物库角色 ID")


class CreateTheaterRequest(BaseModel):
    title: str = Field(default="未命名演出")
    scene: dict = Field(default_factory=dict, description="场景描述 {text, location, ...}")
    mode: str = Field(default="perform", description="perform 演绎 | discuss 讨论")


def _scan_chapters(project: NovelProject) -> list[dict]:
    """扫描工作区 story/ 目录，生成章节状态列表。"""
    ws = Path(project.workspace)
    story_dir = ws / "story"
    chapters: list[dict] = []
    for ch in project.chapters:
        ch_num = f"{int(ch):04d}"
        md = story_dir / ch_num / "chapter.md"
        exists = md.is_file()
        chapters.append({
            "number": int(ch),
            "chapter_number": ch_num,
            "status": "已生成" if exists else "待生成",
            "word_count": len(md.read_text(encoding="utf-8")) if exists else 0,
        })
    return chapters


@router.get("")
async def list_pipeline_projects():
    ensure_dirs()
    return {"projects": [p.to_dict() for p in list_projects()]}


@router.post("")
async def create_project(body: CreateProjectRequest):
    ensure_dirs()
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="书名不能为空")
    chapters = [int(c) for c in body.chapters if str(c).strip().isdigit()]
    if not chapters:
        raise HTTPException(status_code=400, detail="章节列表不能为空")
    if len(chapters) > 50:
        raise HTTPException(status_code=400, detail="章节数不能超过 50")

    project_id = "np-" + uuid.uuid4().hex[:10]
    ws = workspace_path(project_id)
    ws.mkdir(parents=True, exist_ok=True)
    project = NovelProject(
        project_id=project_id,
        name=name,
        premise=body.premise.strip(),
        genre=body.genre.strip(),
        language=body.language.strip() or "中文",
        chapters=chapters,
        target_word_count=body.target_word_count.strip() or "3000-4000",
        estimated_length=body.estimated_length.strip() or "中",
        words_per_chapter=body.words_per_chapter.strip() or "2000-2500",
        human_intent=body.human_intent,
        world_intent=body.world_intent,
        writer_type=body.writer_type.strip() or "single",
        workspace=str(ws),
    )
    project.steps = project.build_steps()
    # 建书时自动创建一个同名剧场世界，挂到作品下（供剧场演绎使用）
    try:
        world = World(name=name, worldview="")
        world.save()
        project.world_id = world.world_id
    except Exception:
        logger.exception("建书时创建剧场世界失败（不影响建书）")
    save_project(project)
    return {"success": True, "project": project.to_dict()}


@router.get("/{project_id}")
async def get_project(project_id: str):
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    return {"project": project.to_dict()}


@router.get("/{project_id}/content")
async def get_project_content(project_id: str):
    """聚合作品内容：世界 + 角色 + 大纲 + 章节 + 演绎会话。"""
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    ws = Path(project.workspace)

    # 世界（关联的剧场 World）
    world = None
    if project.world_id:
        w = World.load(project.world_id)
        if w:
            world = w.to_dict()

    # 角色（人物库）
    characters: list[dict] = []
    if project.character_ids:
        from src.characters.manager import get_character_manager
        mgr = get_character_manager()
        for cid in project.character_ids:
            c = mgr.get(cid)
            if c:
                characters.append(c.to_dict())

    # 大纲摘要（卷纲 + 近纲）
    outline = {"volume_outline": "", "near_term_outline": ""}
    for key, rel in (
        ("volume_outline", "outline/volume_outline.md"),
        ("near_term_outline", "outline/near_term_outline.md"),
    ):
        p = ws / rel
        if p.is_file():
            outline[key] = p.read_text(encoding="utf-8")[:20000]

    # 世界观正文（流水线产出）
    world_foundation = ""
    wf = ws / "meta" / "world_foundation.md"
    if wf.is_file():
        world_foundation = wf.read_text(encoding="utf-8")[:100000]

    # 演绎会话
    theater_sessions: list[dict] = []
    for sid in project.theater_session_ids:
        s = TheaterSession.load(sid)
        if s:
            theater_sessions.append(s.to_dict())

    return {
        "project": project.to_dict(),
        "world": world,
        "characters": characters,
        "outline": outline,
        "world_foundation": world_foundation,
        "chapters": _scan_chapters(project),
        "theater_sessions": theater_sessions,
        "workspace": project.workspace,
        "archive_path": project.archive_path or "",
    }


@router.post("/{project_id}/characters")
async def add_character(project_id: str, body: AddCharacterRequest):
    """把人物库角色关联到作品。"""
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    cid = body.character_id.strip()
    if not cid:
        raise HTTPException(status_code=400, detail="character_id 不能为空")
    from src.characters.manager import get_character_manager
    if get_character_manager().get(cid) is None:
        raise HTTPException(status_code=404, detail=f"角色不存在: {cid}")
    if cid not in project.character_ids:
        project.character_ids.append(cid)
        save_project(project)
    return {"success": True, "character_ids": project.character_ids}


@router.delete("/{project_id}/characters/{character_id}")
async def remove_character(project_id: str, character_id: str):
    """取消作品与角色关联。"""
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    project.character_ids = [c for c in project.character_ids if c != character_id]
    save_project(project)
    return {"success": True, "character_ids": project.character_ids}


@router.post("/{project_id}/theater")
async def create_theater_session(project_id: str, body: CreateTheaterRequest):
    """为作品创建一个剧场演绎会话（用本书世界 + 角色），并挂到作品下。"""
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    if not project.world_id:
        raise HTTPException(status_code=400, detail="作品尚未创建剧场世界")
    session = TheaterSession(
        world_id=project.world_id,
        mode=body.mode or "perform",
        title=body.title.strip() or "未命名演出",
        character_ids=list(project.character_ids),
        scene=body.scene or {},
    )
    session.save()
    if session.session_id not in project.theater_session_ids:
        project.theater_session_ids.append(session.session_id)
        save_project(project)
    return {"success": True, "session": session.to_dict()}


@router.get("/{project_id}/chapters/{chapter}/text")
async def get_chapter_text(project_id: str, chapter: str):
    """读取某一章的正文（chapter.md）。"""
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    ch_num = f"{int(chapter):04d}"
    p = Path(project.workspace) / "story" / ch_num / "chapter.md"
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"第 {int(chapter)} 章尚未生成")
    return {
        "chapter_number": ch_num,
        "content": p.read_text(encoding="utf-8"),
    }


@router.delete("/{project_id}")
async def delete_project(project_id: str, request: Request):
    runner = _get_runner(request)
    if runner.is_running(project_id):
        raise HTTPException(status_code=409, detail="小说正在连跑，请先停止")
    from .models import project_path
    path = project_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="小说项目不存在")
    import shutil
    shutil.rmtree(path.parent, ignore_errors=True)
    return {"success": True, "message": "小说项目已删除"}


@router.post("/{project_id}/run")
async def run_pipeline(project_id: str, request: Request, body: RunRequest = RunRequest()):
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    runner = _get_runner(request)
    result = runner.start(project, reset=body.reset)
    if not result["success"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@router.post("/{project_id}/run-step")
async def run_single_step(project_id: str, request: Request, body: RunStepRequest):
    """只运行流水线中的某一个步骤（作品工作台原地生成用）。"""
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    runner = _get_runner(request)
    result = runner.start_single(project, body.step_key)
    if not result["success"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@router.post("/{project_id}/stop")
async def stop_pipeline(project_id: str, request: Request):
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    runner = _get_runner(request)
    return await runner.stop(project_id)


@router.get("/{project_id}/text")
async def get_full_text(project_id: str):
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    path = Path(project.final_text_path) if project.final_text_path else None
    if path is None or not path.exists():
        path = workspace_path(project_id) / "novel" / "完整文本.md"
        novel_dir = path.parent
        if novel_dir.exists():
            candidates = sorted(novel_dir.glob("*.md"))
            path = candidates[0] if candidates else None
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="完整文本尚未生成")
    return {
        "project_id": project_id,
        "name": project.name,
        "content": path.read_text(encoding="utf-8"),
        "path": str(path),
        "archive_path": project.archive_path or "",
    }


@router.get("/{project_id}/text/download")
async def download_full_text(project_id: str):
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    path = Path(project.final_text_path) if project.final_text_path else None
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="完整文本尚未生成")
    safe = re.sub(r'[\\/:*?"<>|]', "_", project.name or "小说")
    return FileResponse(
        str(path),
        media_type="text/markdown; charset=utf-8",
        filename=f"《{safe}》完整文本.md",
    )


@router.get("/{project_id}/files")
async def list_project_files(project_id: str):
    """列出项目工作区里的主要产出文件（世界观/大纲/章节/完整文本）。"""
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    ws = Path(project.workspace)
    if not ws.exists():
        return {"files": []}
    files: list[dict] = []
    for sub in ("meta", "outline", "story", "novel", "archive", "cache"):
        base = ws / sub
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if f.is_file() and f.stat().st_size <= 3 * 1024 * 1024:
                files.append({
                    "path": str(f.relative_to(ws)).replace("\\", "/"),
                    "size": f.stat().st_size,
                })
    return {"files": files, "archive_root": str(NOVEL_ARCHIVE_DIR)}
