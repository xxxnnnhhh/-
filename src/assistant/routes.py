"""书架总大脑 REST API。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.novel_pipeline.models import load_project, save_project
from .brain import chat as brain_chat
from .brain import diagnose as brain_diagnose
from .brain import execute_chapter_body_update, apply_workflow_node_update, describe_workflows

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


def _get_project(project_id: str):
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="小说项目不存在")
    return project


class ChatMessage(BaseModel):
    role: str = "user"
    content: str = ""


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    model_override: str | None = None


class ConfirmActionRequest(BaseModel):
    operation: str = Field(description="chapter_body_update | run_step")
    arguments: dict = Field(default_factory=dict)


class SetSkillsRequest(BaseModel):
    skill_ids: list[str] = Field(default_factory=list)


class AssistantSettingsRequest(BaseModel):
    assistant_enabled: bool | None = None
    assistant_model: str | None = None


@router.post("/projects/{project_id}/chat")
async def assistant_chat(project_id: str, body: ChatRequest, request: Request):
    """与总大脑对话：返回 {reply, action?}。"""
    project = _get_project(project_id)
    messages = [{"role": m.role, "content": m.content} for m in body.messages if m.content.strip()]
    if not messages:
        raise HTTPException(status_code=400, detail="消息不能为空")
    result = await brain_chat(project, messages, model_override=body.model_override)
    return {"project_id": project_id, **result}


@router.post("/projects/{project_id}/actions/confirm")
async def confirm_action(project_id: str, body: ConfirmActionRequest, request: Request):
    """确认并执行助手提案的动作。"""
    project = _get_project(project_id)
    op = body.operation.strip()
    args = body.arguments or {}
    if op == "chapter_body_update":
        result = execute_chapter_body_update(project, args)
    elif op == "run_step":
        step_key = str(args.get("step_key", "")).strip()
        if not step_key:
            raise HTTPException(status_code=400, detail="缺少 step_key")
        runner = request.app.state.novel_pipeline_runner
        result = runner.start_single(project, step_key)
        if not result.get("success"):
            raise HTTPException(status_code=409, detail=result.get("message", "启动失败"))
    elif op == "workflow_update_node":
        manager = request.app.state.workflow_manager
        result = apply_workflow_node_update(manager, args)
        if not result.get("success"):
            raise HTTPException(status_code=409, detail=result.get("message", "修改失败"))
    elif op == "describe_workflows":
        result = {
            "success": True,
            "message": "已读取 7 个工作流结构",
            "result": describe_workflows(),
        }
    elif op == "run_pipeline":
        runner = request.app.state.novel_pipeline_runner
        result = runner.start(project, reset=bool(args.get("reset", False)))
        if not result.get("success"):
            raise HTTPException(status_code=409, detail=result.get("message", "启动失败"))
    else:
        raise HTTPException(status_code=400, detail=f"未知动作: {op}")
    return {"project_id": project_id, "operation": op, **result}


@router.post("/projects/{project_id}/diagnose")
async def diagnose_project(project_id: str, body: ChatRequest = ChatRequest()):
    """流水线失败后自动诊断：返回 {diagnosis, actions}。"""
    project = _get_project(project_id)
    result = await brain_diagnose(project, model_override=body.model_override)
    return {"project_id": project_id, **result}


@router.post("/projects/{project_id}/settings")
async def update_assistant_settings(project_id: str, body: AssistantSettingsRequest):
    """更新总大脑设置（AI 开关 / 模型）。"""
    project = _get_project(project_id)
    if body.assistant_enabled is not None:
        project.assistant_enabled = bool(body.assistant_enabled)
    if body.assistant_model is not None:
        project.assistant_model = body.assistant_model.strip()
    save_project(project)
    return {
        "success": True,
        "assistant_enabled": project.assistant_enabled,
        "assistant_model": project.assistant_model,
    }


@router.post("/projects/{project_id}/skills")
async def set_project_skills(project_id: str, body: SetSkillsRequest):
    """设置作品挂载的写作风格 Skills。"""
    project = _get_project(project_id)
    project.skill_ids = [s for s in body.skill_ids if s.strip()]
    save_project(project)
    return {"success": True, "skill_ids": project.skill_ids}


@router.get("/projects/{project_id}/skills")
async def get_project_skills(project_id: str, request: Request):
    """返回作品挂载的 Skills 详情 + 技能库中可用的写作类 Skills。"""
    project = _get_project(project_id)
    mounted: list[dict] = []
    available: list[dict] = []
    try:
        from src.skills.loader import SkillLoader
        from src.config import SKILLS_DIR
        loader = SkillLoader(SKILLS_DIR)
        all_skills = {s.id: s for s in loader.load_all()}
        mounted = [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "content": s.content,
            }
            for s in (all_skills.get(sid) for sid in project.skill_ids)
            if s is not None
        ]
        available = [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "category": s.category.value,
                "tags": s.tags,
                "enabled": s.enabled,
            }
            for s in all_skills.values()
            if s.enabled and (not s.tags or "写作" in "".join(s.tags))
        ]
    except Exception:
        logger.exception("读取 Skills 失败")
    return {
        "project_id": project_id,
        "mounted": mounted,
        "available": available,
    }
