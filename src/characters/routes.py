"""人物库 REST API — /api/characters/*"""
from __future__ import annotations

import logging
import subprocess

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.characters.manager import get_character_manager
from src.characters.logs import log_file_for

logger = logging.getLogger("characters")

router = APIRouter(prefix="/api/characters", tags=["characters"])


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
    ratio_descriptions: dict = Field(default_factory=dict)
    traits: list[TraitIn] = Field(default_factory=list)
    events: list[EventIn] = Field(default_factory=list)
    hard_rules: list[str] = Field(default_factory=list)
    soft_rules: list[str] = Field(default_factory=list)
    temperature: float = 0.9
    model_name: str | None = None
    types: list[str] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)
    abilities: list[dict] = Field(default_factory=list)
    equipment: list[dict] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=4000,
        description="对话内容（最长 4000 字）",
    )
    search: bool = Field(default=False, description="是否联网搜索最新资料")


def _with_log_path(character: dict) -> dict:
    result = dict(character)
    result["log_path"] = str(log_file_for(character.get("name", "")))
    return result


@router.post("")
async def create_character(body: CharacterIn):
    character = get_character_manager().save(body.model_dump())
    return {"success": True, "character": character.to_dict()}


@router.get("")
async def list_characters():
    mgr = get_character_manager()
    characters = [_with_log_path(c) for c in mgr.list_all()]
    return {"characters": characters, "total": len(mgr.characters)}


@router.get("/{character_id}")
async def get_character(character_id: str):
    character = get_character_manager().get(character_id)
    if not character:
        raise HTTPException(status_code=404, detail=f"未找到角色 {character_id}")
    return {"character": _with_log_path(character.to_dict())}


@router.delete("/{character_id}")
async def delete_character(character_id: str):
    if not get_character_manager().delete(character_id):
        raise HTTPException(status_code=404, detail=f"未找到角色 {character_id}")
    return {"success": True, "message": f"角色 {character_id} 已删除"}


@router.post("/{character_id}/memory/clear")
async def clear_character_memory(character_id: str):
    character = get_character_manager().get(character_id)
    if not character:
        raise HTTPException(status_code=404, detail=f"未找到角色 {character_id}")
    from src.characters.memory import clear_memory
    clear_memory(character)
    return {"success": True, "message": f"角色 {character_id} 的人物日志已清空"}


@router.post("/{character_id}/chat")
async def chat_with_character(character_id: str, body: ChatRequest):
    from src.characters.chat import run_chat

    character = get_character_manager().get(character_id)
    if not character:
        raise HTTPException(status_code=404, detail=f"未找到角色 {character_id}")
    result = await run_chat(character, body.message, search=body.search)
    return {"success": True, **result}


@router.post("/{character_id}/chat/export")
async def export_chat(character_id: str):
    from src.characters.chat import export_chat_document

    character = get_character_manager().get(character_id)
    if not character:
        raise HTTPException(status_code=404, detail=f"未找到角色 {character_id}")
    result = export_chat_document(character)
    return {"success": True, **result}


@router.post("/{character_id}/log/open")
async def open_character_log(character_id: str):
    character = get_character_manager().get(character_id)
    if not character:
        raise HTTPException(status_code=404, detail=f"未找到角色 {character_id}")
    path = log_file_for(character.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"# {character.name} 的人物日志\n", encoding="utf-8")
    try:
        subprocess.Popen(["explorer", "/select,", str(path)])
    except OSError as e:
        logger.warning(f"打开日志文件夹失败: {e}")
    return {"success": True, "log_path": str(path)}
