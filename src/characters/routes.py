"""人物库 REST API — /api/characters/*"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.characters.manager import get_character_manager

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


@router.post("")
async def create_character(body: CharacterIn):
    character = get_character_manager().save(body.model_dump())
    return {"success": True, "character": character.to_dict()}


@router.get("")
async def list_characters():
    mgr = get_character_manager()
    return {"characters": mgr.list_all(), "total": len(mgr.characters)}


@router.get("/{character_id}")
async def get_character(character_id: str):
    character = get_character_manager().get(character_id)
    if not character:
        raise HTTPException(status_code=404, detail=f"未找到角色 {character_id}")
    return {"character": character.to_dict()}


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
