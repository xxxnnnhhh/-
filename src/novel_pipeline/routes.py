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
    save_project(project)
    return {"success": True, "project": project.to_dict()}


@router.get("/{project_id}")
async def get_project(project_id: str):
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    return {"project": project.to_dict()}


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
