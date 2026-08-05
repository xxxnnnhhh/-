"""故事机器 REST API — /api/story/*"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("story")

router = APIRouter(prefix="/api/story", tags=["story"])


def _get_story_manager(request: Request):
    if not hasattr(request.app.state, "story_manager"):
        raise HTTPException(status_code=503, detail="故事机器管理器未初始化")
    return request.app.state.story_manager


# ============ 请求模型 ============

class TraitIn(BaseModel):
    name: str
    id_delta: float = 0
    ego_delta: float = 0
    superego_delta: float = 0
    emotion_amplifier: float = 1.0
    regress_rate: float | None = None


class EventIn(BaseModel):
    title: str
    description: str = ""
    triggers: list[str] = Field(default_factory=list)
    emotion_shift: dict = Field(default_factory=dict)
    ratio_rebase: dict = Field(default_factory=dict)
    decay: float = 0.02


class CharacterIn(BaseModel):
    character_id: str = ""
    name: str
    base_ratio: dict = Field(default_factory=lambda: {"id": 33, "ego": 34, "superego": 33})
    traits: list[TraitIn] = Field(default_factory=list)
    events: list[EventIn] = Field(default_factory=list)
    hard_rules: list[str] = Field(default_factory=list)
    soft_rules: list[str] = Field(default_factory=list)
    temperature: float = 0.9
    model_name: str | None = None


class CreateStoryRequest(BaseModel):
    title: str
    scene: dict = Field(default_factory=dict)
    character_ids: list[str] = Field(min_length=1)
    max_rounds: int = Field(default=8, ge=1, le=50)
    narrator_enabled: bool = True


class InjectRequest(BaseModel):
    content: str = Field(min_length=1)


class EmotionRequest(BaseModel):
    character_id: str
    emotion: dict | None = None
    ratios: dict | None = None
    clear: bool = False


# ============ 角色 ============

@router.post("/characters")
async def create_character(body: CharacterIn, request: Request):
    mgr = _get_story_manager(request)
    character = mgr.save_character(body.model_dump())
    return {"success": True, "character": character.to_dict()}


@router.get("/characters")
async def list_characters(request: Request):
    mgr = _get_story_manager(request)
    return {"characters": mgr.list_characters(), "total": len(mgr.characters)}


@router.get("/characters/{character_id}")
async def get_character(character_id: str, request: Request):
    mgr = _get_story_manager(request)
    character = mgr.get_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail=f"未找到角色 {character_id}")
    return {"character": character.to_dict()}


@router.delete("/characters/{character_id}")
async def delete_character(character_id: str, request: Request):
    mgr = _get_story_manager(request)
    if not mgr.delete_character(character_id):
        raise HTTPException(status_code=404, detail=f"未找到角色 {character_id}")
    return {"success": True, "message": f"角色 {character_id} 已删除"}


# ============ 会话 ============

@router.post("/sessions")
async def create_story(body: CreateStoryRequest, request: Request):
    mgr = _get_story_manager(request)
    session = mgr.create_session(
        title=body.title,
        scene=body.scene,
        character_ids=body.character_ids,
        max_rounds=body.max_rounds,
        narrator_enabled=body.narrator_enabled,
    )
    if not session.character_ids:
        raise HTTPException(status_code=400, detail="所选角色不存在或为空")
    return {"success": True, "session": session.get_summary()}


@router.get("/sessions")
async def list_stories(request: Request):
    mgr = _get_story_manager(request)
    return {"sessions": mgr.list_all(), "total": len(mgr.sessions)}


@router.get("/sessions/{session_id}")
async def get_story(session_id: str, request: Request):
    mgr = _get_story_manager(request)
    session = mgr.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"未找到故事 {session_id}")
    data = session.to_dict()
    data["characters"] = [
        c.to_dict() for cid in session.character_ids
        if (c := mgr.get_character(cid))
    ]
    return data


@router.delete("/sessions/{session_id}")
async def delete_story(session_id: str, request: Request):
    mgr = _get_story_manager(request)
    result = await mgr.delete(session_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ============ 生命周期 ============

@router.post("/sessions/{session_id}/start")
async def start_story(session_id: str, request: Request):
    mgr = _get_story_manager(request)
    result = await mgr.start(session_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/sessions/{session_id}/stop")
async def stop_story(session_id: str, request: Request):
    mgr = _get_story_manager(request)
    result = await mgr.stop(session_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/sessions/{session_id}/pause")
async def pause_story(session_id: str, request: Request):
    mgr = _get_story_manager(request)
    result = await mgr.pause(session_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/sessions/{session_id}/resume")
async def resume_story(session_id: str, request: Request):
    mgr = _get_story_manager(request)
    result = await mgr.resume(session_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/sessions/{session_id}/inject")
async def inject_story(session_id: str, body: InjectRequest, request: Request):
    mgr = _get_story_manager(request)
    result = await mgr.inject(session_id, body.content)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/sessions/{session_id}/emotions")
async def set_emotion(session_id: str, body: EmotionRequest, request: Request):
    mgr = _get_story_manager(request)
    result = await mgr.set_emotion(
        session_id,
        body.character_id,
        emotion=body.emotion,
        ratios=body.ratios,
        clear=body.clear,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/sessions/{session_id}/export")
async def export_story(session_id: str, request: Request):
    mgr = _get_story_manager(request)
    markdown = mgr.export_markdown(session_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail=f"未找到故事 {session_id}")
    return {"success": True, "markdown": markdown}

