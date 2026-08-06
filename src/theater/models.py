"""剧场数据模型：World（世界）与 TheaterSession（剧场会话）。"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.config import DATA_DIR

logger = logging.getLogger("theater")

WORLDS_DIR = Path(DATA_DIR) / "worlds"
THEATER_SESSIONS_DIR = Path(DATA_DIR) / "sessions"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class World:
    """一个世界：世界观约束 + 角色集合 + Skills 挂载 + 已发生剧情。"""
    world_id: str = ""
    name: str = "未命名世界"
    worldview: str = ""  # 世界观正文（规则/力量体系/禁忌/人物关系）
    skill_ids: list[str] = field(default_factory=list)  # 挂到世界的写作风格 Skills
    character_ids: list[str] = field(default_factory=list)
    history: list[str] = field(default_factory=list)  # 已发生剧情（防前后矛盾）
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.world_id:
            self.world_id = f"wx-{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = _now()
        self.updated_at = _now()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "World":
        w = cls(
            world_id=data.get("world_id", ""),
            name=data.get("name", "未命名世界"),
            worldview=data.get("worldview", ""),
            skill_ids=list(data.get("skill_ids", []) or []),
            character_ids=list(data.get("character_ids", []) or []),
            history=list(data.get("history", []) or []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
        return w

    def save(self) -> bool:
        WORLDS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = WORLDS_DIR / f"{self.world_id}.json"
        tmp_path = file_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(str(tmp_path), str(file_path))
            return True
        except (IOError, OSError) as e:
            logger.error(f"保存世界 {self.name} 失败: {e}")
            return False

    @classmethod
    def load(cls, world_id: str) -> "World | None":
        file_path = WORLDS_DIR / f"{world_id}.json"
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.error(f"加载世界 {world_id} 失败: {e}")
            return None


@dataclass
class TheaterSession:
    """一场剧场演出：绑定世界 + 模式 + 预读取状态 + 共识摘要。"""
    session_id: str = ""
    world_id: str = ""
    mode: str = "perform"  # "discuss" 讨论 | "perform" 演绎
    title: str = "未命名演出"
    character_ids: list[str] = field(default_factory=list)
    scene: dict = field(default_factory=dict)
    pre_read_done: bool = False
    pre_read_steps: list[dict] = field(default_factory=list)  # [{key,label,status}]
    consensus: str = ""  # AI 预读取生成的共识摘要
    battle_ratio: int = 70  # 文字演绎占比（0-100），数值判定 = 100 - ratio
    status: str = "waiting"  # waiting | discussing | ended
    record: list[str] = field(default_factory=list)  # 演出记录（旁白/角色行）
    created_at: str = ""

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"th-{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = _now()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TheaterSession":
        return cls(
            session_id=data.get("session_id", ""),
            world_id=data.get("world_id", ""),
            mode=data.get("mode", "perform"),
            title=data.get("title", "未命名演出"),
            character_ids=list(data.get("character_ids", []) or []),
            scene=dict(data.get("scene", {}) or {}),
            pre_read_done=bool(data.get("pre_read_done", False)),
            pre_read_steps=list(data.get("pre_read_steps", []) or []),
            consensus=data.get("consensus", ""),
            battle_ratio=int(data.get("battle_ratio", 70) or 70),
            status=data.get("status", "waiting"),
            record=list(data.get("record", []) or []),
            created_at=data.get("created_at", ""),
        )

    def save(self) -> bool:
        THEATER_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = THEATER_SESSIONS_DIR / f"{self.session_id}.json"
        tmp_path = file_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(str(tmp_path), str(file_path))
            return True
        except (IOError, OSError) as e:
            logger.error(f"保存剧场会话 {self.session_id} 失败: {e}")
            return False

    @classmethod
    def load(cls, session_id: str) -> "TheaterSession | None":
        file_path = THEATER_SESSIONS_DIR / f"{session_id}.json"
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.error(f"加载剧场会话 {session_id} 失败: {e}")
            return None
