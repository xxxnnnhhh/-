"""把流水线角色（skeleton.json）自动归档进人物库，并关联到本书。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .models import save_project

if TYPE_CHECKING:
    from .models import NovelProject

logger = logging.getLogger(__name__)


def import_characters(project: "NovelProject", *, force: bool = False) -> dict:
    """读取 workspace/cache/character/skeleton.json，转成人物库 Character 并关联本书。

    Returns:
        {"success": True, "imported": [name...], "skipped": [name...]}
    """
    from src.characters.manager import get_character_manager
    from src.characters.models import Character

    ws = Path(project.workspace)
    skeleton_file = ws / "cache" / "character" / "skeleton.json"
    if not skeleton_file.is_file():
        return {"success": False, "message": "尚未生成角色骨架（请先跑「角色创建」工作流）"}
    try:
        data = json.loads(skeleton_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"success": False, "message": f"角色骨架解析失败：{exc}"}

    mgr = get_character_manager()
    imported: list[str] = []
    skipped: list[str] = []
    by_name = {
        str(c.name): c.character_id
        for c in getattr(mgr, "characters", {}).values()
    }
    for item in (data.get("characters") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        # 同名且已关联本书的角色跳过（避免重复归档）
        existing_id = by_name.get(name)
        if not force and existing_id is not None and existing_id in project.character_ids:
            skipped.append(name)
            continue
        char = mgr.get(existing_id) if existing_id else None
        if char is None or force:
            role = str(item.get("role", ""))
            types = ["plot", "talk"]
            if "主" in role:
                types = ["fight", "plot", "talk"]
            summary = str(item.get("essence", "")).strip() or f"{name}：{role}"
            char = Character(name=name, types=types, summary=summary)
            saved = mgr.save(char.to_dict())
            by_name[name] = saved.character_id
            char = saved
        else:
            char.summary = str(item.get("essence", "")).strip() or char.summary
            mgr.save(char.to_dict())
        if char.character_id not in project.character_ids:
            project.character_ids.append(char.character_id)
        imported.append(name)
    save_project(project)
    return {"success": True, "imported": imported, "skipped": skipped}
