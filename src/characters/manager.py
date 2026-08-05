"""人物库管理器 — 全局共享的角色注册表与持久化。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.characters.models import CHARACTERS_DIR, Character

logger = logging.getLogger("characters")


class CharacterManager:
    def __init__(self):
        self.characters: dict[str, Character] = {}

    def save(self, data: dict) -> Character:
        cid = data.get("character_id", "")
        if cid and cid in self.characters:
            existing = self.characters[cid]
            for key, value in data.items():
                if key in ("traits", "events"):
                    continue
                if hasattr(existing, key):
                    setattr(existing, key, value)
            if "traits" in data:
                from src.characters.models import Trait
                existing.traits = [Trait.from_dict(t) for t in data["traits"]]
            if "events" in data:
                from src.characters.models import StoryEvent
                existing.events = [StoryEvent.from_dict(e) for e in data["events"]]
            existing.updated_at = datetime.now(timezone.utc).isoformat()
            character = existing
        else:
            character = Character.from_dict(data)
        character.save()
        self.characters[character.character_id] = character
        return character

    def get(self, character_id: str) -> Character | None:
        return self.characters.get(character_id)

    def delete(self, character_id: str) -> bool:
        character = self.characters.pop(character_id, None)
        if not character:
            return False
        file_path = CHARACTERS_DIR / f"{character_id}.json"
        if file_path.exists():
            file_path.unlink()
        return True

    def list_all(self) -> list[dict]:
        return [c.to_dict() for c in self.characters.values()]

    def load_all(self) -> None:
        if not CHARACTERS_DIR.exists():
            return
        for file_path in CHARACTERS_DIR.glob("*.json"):
            try:
                character = Character.load(file_path.stem)
                if character:
                    self.characters[character.character_id] = character
            except Exception as e:
                logger.error(f"加载角色 {file_path.stem} 失败: {e}")


_manager: CharacterManager | None = None


def get_character_manager() -> CharacterManager:
    """进程内共享单例。"""
    global _manager
    if _manager is None:
        _manager = CharacterManager()
    return _manager

