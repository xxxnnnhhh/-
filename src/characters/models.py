"""人物库核心数据模型：Character / Trait / StoryEvent。

一个角色是"活人"：三我占比为底色，特质/事件/规则可自由编辑，
情绪状态在对话中持续演化。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from src.config import DATA_DIR

logger = logging.getLogger("characters")

CHARACTERS_DIR = Path(DATA_DIR) / "characters"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Trait:
    """性格特质：对三我基准的增量 + 动态参数。"""
    name: str
    id_delta: float = 0.0
    ego_delta: float = 0.0
    superego_delta: float = 0.0
    emotion_amplifier: float = 1.0
    regress_rate: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Trait":
        return cls(
            name=data.get("name", "未命名特质"),
            id_delta=float(data.get("id_delta", 0) or 0),
            ego_delta=float(data.get("ego_delta", 0) or 0),
            superego_delta=float(data.get("superego_delta", 0) or 0),
            emotion_amplifier=float(data.get("emotion_amplifier", 1.0) or 1.0),
            regress_rate=(
                float(data["regress_rate"]) if data.get("regress_rate") is not None else None
            ),
        )


@dataclass
class StoryEvent:
    """重大事件：命中触发情境时影响情绪与人格，随时间演变。"""
    title: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    emotion_shift: dict = field(default_factory=dict)
    ratio_rebase: dict = field(default_factory=dict)
    decay: float = 0.02
    active_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "StoryEvent":
        return cls(
            title=data.get("title", "未命名事件"),
            description=data.get("description", ""),
            triggers=list(data.get("triggers", []) or []),
            emotion_shift=dict(data.get("emotion_shift", {}) or {}),
            ratio_rebase=dict(data.get("ratio_rebase", {}) or {}),
            decay=float(data.get("decay", 0.02) or 0),
            active_count=int(data.get("active_count", 0) or 0),
        )


@dataclass
class Character:
    """虚拟人物：三我占比为底色，特质/事件/规则可自由编辑。"""
    character_id: str = ""
    name: str = "未命名角色"
    base_ratio: dict = field(default_factory=lambda: {"id": 33, "ego": 34, "superego": 33})
    ratio_descriptions: dict = field(default_factory=dict)  # {"id": "冲动直率", "ego": "...", "superego": "..."}
    traits: list[Trait] = field(default_factory=list)
    events: list[StoryEvent] = field(default_factory=list)
    hard_rules: list[str] = field(default_factory=list)
    soft_rules: list[str] = field(default_factory=list)
    temperature: float = 0.9
    model_name: str | None = None
    # ==== 剧场增强字段 ====
    types: list[str] = field(default_factory=list)  # ["fight","plot","talk"] 战斗/剧情/对话
    stats: dict = field(default_factory=lambda: {
        "力量": 50, "敏捷": 50, "体质": 50, "智力": 50, "精神": 50,
    })  # 身体素质五维
    abilities: list[dict] = field(default_factory=list)  # [{"name":"伞刃精通","level":3}]
    equipment: list[dict] = field(default_factory=list)  # [{"name":"青骨伞","effect":"力量+5","slot":"武器"}]
    skill_ids: list[str] = field(default_factory=list)  # 挂载的写作风格 Skills
    emotion_state: dict = field(default_factory=dict)
    pinned_emotion: dict | None = None
    pinned_ratios: dict | None = None
    current_ratio: dict | None = None
    pressure: float = 0.0
    summary: str = ""
    memory_logs: list[dict] = field(default_factory=list)  # 人物日志：跨会话记忆
    chat_history: list[dict] = field(default_factory=list)  # 与用户的对话记录（最近 N 条）
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.character_id:
            self.character_id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = _now()
        self.updated_at = _now()
        self.current_ratio = dict(self.base_ratio)

    def to_dict(self) -> dict:
        return {
            "character_id": self.character_id,
            "name": self.name,
            "base_ratio": dict(self.base_ratio),
            "ratio_descriptions": dict(self.ratio_descriptions),
            "traits": [t.to_dict() for t in self.traits],
            "events": [e.to_dict() for e in self.events],
            "hard_rules": list(self.hard_rules),
            "soft_rules": list(self.soft_rules),
            "temperature": self.temperature,
            "model_name": self.model_name,
            "types": list(self.types),
            "stats": dict(self.stats),
            "abilities": [dict(a) for a in self.abilities],
            "equipment": [dict(e) for e in self.equipment],
            "skill_ids": list(self.skill_ids),
            "emotion_state": dict(self.emotion_state),
            "pinned_emotion": dict(self.pinned_emotion) if self.pinned_emotion else None,
            "pinned_ratios": dict(self.pinned_ratios) if self.pinned_ratios else None,
            "current_ratio": dict(self.current_ratio) if self.current_ratio else dict(self.base_ratio),
            "pressure": self.pressure,
            "summary": self.summary,
            "memory_logs": list(self.memory_logs),
            "chat_history": list(self.chat_history),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Character":
        c = cls(
            character_id=data.get("character_id", ""),
            name=data.get("name", "未命名角色"),
            base_ratio=dict(data.get("base_ratio", {"id": 33, "ego": 34, "superego": 33})),
            ratio_descriptions=dict(data.get("ratio_descriptions", {}) or {}),
            traits=[Trait.from_dict(t) for t in data.get("traits", [])],
            events=[StoryEvent.from_dict(e) for e in data.get("events", [])],
            hard_rules=list(data.get("hard_rules", []) or []),
            soft_rules=list(data.get("soft_rules", []) or []),
            temperature=float(data.get("temperature", 0.9)),
            model_name=data.get("model_name"),
            types=list(data.get("types", []) or []),
            stats=dict(data.get("stats", {"力量": 50, "敏捷": 50, "体质": 50, "智力": 50, "精神": 50})),
            abilities=[dict(a) for a in (data.get("abilities", []) or [])],
            equipment=[dict(e) for e in (data.get("equipment", []) or [])],
            skill_ids=list(data.get("skill_ids", []) or []),
            emotion_state=dict(data.get("emotion_state", {}) or {}),
            pinned_emotion=dict(data["pinned_emotion"]) if data.get("pinned_emotion") else None,
            pinned_ratios=dict(data["pinned_ratios"]) if data.get("pinned_ratios") else None,
            current_ratio=dict(data["current_ratio"]) if data.get("current_ratio") else None,
            pressure=float(data.get("pressure", 0.0) or 0.0),
            summary=data.get("summary", ""),
            memory_logs=list(data.get("memory_logs", []) or []),
            chat_history=list(data.get("chat_history", []) or []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
        c.updated_at = data.get("updated_at", _now())
        return c

    def save(self) -> bool:
        CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = CHARACTERS_DIR / f"{self.character_id}.json"
        tmp_path = file_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(str(tmp_path), str(file_path))
            return True
        except (IOError, OSError) as e:
            logger.error(f"保存角色 {self.name} 失败: {e}")
            return False

    @classmethod
    def load(cls, character_id: str) -> "Character | None":
        file_path = CHARACTERS_DIR / f"{character_id}.json"
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.error(f"加载角色 {character_id} 失败: {e}")
            return None
