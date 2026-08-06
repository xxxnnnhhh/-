"""剧场 REST 路由：世界 CRUD、会话、预读取、战斗、幕后聊天。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.theater.manager import get_theater_manager

router = APIRouter(prefix="/api/theater", tags=["theater"])


def _mgr(request: Request):
    if not hasattr(request.app.state, "theater_manager"):
        request.app.state.theater_manager = get_theater_manager()
    return request.app.state.theater_manager


# ---------- 世界 ----------

class WorldCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    worldview: str = ""
    skill_ids: list[str] = Field(default_factory=list)


class WorldUpdateRequest(BaseModel):
    name: str | None = None
    worldview: str | None = None
    skill_ids: list[str] | None = None
    character_ids: list[str] | None = None
    history: list[str] | None = None


@router.get("/worlds")
async def list_worlds(request: Request):
    return {"worlds": _mgr(request).list_worlds()}


@router.post("/worlds")
async def create_world(body: WorldCreateRequest, request: Request):
    w = _mgr(request).create_world(name=body.name, worldview=body.worldview, skill_ids=body.skill_ids)
    return {"success": True, "world": w.to_dict()}


@router.put("/worlds/{world_id}")
async def update_world(world_id: str, body: WorldUpdateRequest, request: Request):
    w = _mgr(request).update_world(world_id, **body.model_dump(exclude_none=True))
    if not w:
        raise HTTPException(status_code=404, detail=f"世界不存在: {world_id}")
    return {"success": True, "world": w.to_dict()}


@router.delete("/worlds/{world_id}")
async def delete_world(world_id: str, request: Request):
    ok = _mgr(request).delete_world(world_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"世界不存在: {world_id}")
    return {"success": True}


# ---------- 剧场会话 ----------

class TheaterCreateRequest(BaseModel):
    world_id: str
    mode: str = "perform"
    title: str = "未命名演出"
    character_ids: list[str] = Field(default_factory=list)
    scene: dict = Field(default_factory=dict)
    battle_ratio: int = Field(default=70, ge=0, le=100)


class RatioRequest(BaseModel):
    ratio: int = Field(ge=0, le=100)


class BattleRequest(BaseModel):
    attacker_id: str
    defender_id: str = ""
    action: str = "发起攻击"
    attack_stat: str = "力量"
    defense_stat: str = "敏捷"


class BackstageChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class PerformRequest(BaseModel):
    director: str = Field(default="", max_length=2000)


@router.get("/sessions")
async def list_sessions(request: Request):
    return {"sessions": _mgr(request).list_sessions()}


@router.post("/sessions")
async def create_session(body: TheaterCreateRequest, request: Request):
    mgr = _mgr(request)
    if not mgr.get_world(body.world_id):
        raise HTTPException(status_code=404, detail=f"世界不存在: {body.world_id}")
    s = mgr.create_session(
        world_id=body.world_id,
        mode=body.mode,
        title=body.title,
        character_ids=body.character_ids,
        scene=body.scene,
        battle_ratio=body.battle_ratio,
    )
    return {"success": True, "session": s.to_dict()}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    s = _mgr(request).get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return {"session": s.to_dict()}


@router.post("/sessions/{session_id}/pre-read")
async def pre_read(session_id: str, request: Request):
    result = await _mgr(request).pre_read(session_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.put("/sessions/{session_id}/battle-ratio")
async def set_battle_ratio(session_id: str, body: RatioRequest, request: Request):
    ok = _mgr(request).set_battle_ratio(session_id, body.ratio)
    if not ok:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return {"success": True, "ratio": body.ratio}


@router.post("/sessions/{session_id}/battle")
async def battle_action(session_id: str, body: BattleRequest, request: Request):
    result = await _mgr(request).battle_action(
        session_id,
        attacker_id=body.attacker_id,
        defender_id=body.defender_id,
        action=body.action,
        attack_stat=body.attack_stat,
        defense_stat=body.defense_stat,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/sessions/{session_id}/perform")
async def perform_round(session_id: str, body: PerformRequest | None = None, request: Request = None):
    """执行一轮演出（旁白 + 角色四通道，AI 生成；战斗场景为小说式打斗描写）。"""
    director = body.director if body else ""
    result = await _mgr(request).perform_round(session_id, director=director)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ---------- 幕后聊天 ----------

@router.post("/sessions/{session_id}/backstage")
async def backstage_chat(session_id: str, body: BackstageChatRequest, request: Request):
    """与幕后 AI 聊天：讨论剧情 / 补设定 / 指挥演出。"""
    from src.core.llm_client import create_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    mgr = _mgr(request)
    s = mgr.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    world = mgr.get_world(s.world_id)
    context = f"世界：{world.name if world else '未知'}\n世界观：{world.worldview if world else ''}"
    try:
        llm = create_llm(model_params={"temperature": 0.7}, streaming=False)
        resp = await llm.ainvoke([
            SystemMessage(content="你是剧场的幕后 AI 助手。根据世界观与演出上下文回答用户的剧情讨论、设定补充或指挥请求。"
                                  "涉及世界观冲突时提示用户，不擅自改动既定设定。用中文回答。" + context),
            HumanMessage(content=body.message),
        ])
        return {"success": True, "reply": str(resp.content).strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"幕后聊天失败: {e}")
