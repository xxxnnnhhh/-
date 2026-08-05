"""故事机器核心数据模型。

与 Roundtable 独立：Seat 是讨论席位，Character 是一个"活人"——
携带三我占比、特质、重大事件、规则、情绪状态。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from src.config import DATA_DIR, SESSIONS_DIR

logger = logging.getLogger("story")

CHARACTERS_DIR = Path(DATA_DIR) / "characters"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# 特质 / 事件 / 角色
# ============================================================

@dataclass
class Trait:
    """性格特质：对三我基准的增量 + 动态参数。"""
    name: str
    id_delta: float = 0.0          # 本我基准增量
    ego_delta: float = 0.0         # 自我基准增量
    superego_delta: float = 0.0    # 超我基准增量
    emotion_amplifier: float = 1.0  # 情绪放大系数
    regress_rate: float | None = None  # 覆盖默认回归率

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
    triggers: list[str] = field(default_factory=list)  # 关键词
    emotion_shift: dict = field(default_factory=dict)  # {"anger": 0.35, ...}
    ratio_rebase: dict = field(default_factory=dict)   # {"id": 5, "superego": 8}
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
    traits: list[Trait] = field(default_factory=list)
    events: list[StoryEvent] = field(default_factory=list)
    hard_rules: list[str] = field(default_factory=list)
    soft_rules: list[str] = field(default_factory=list)
    temperature: float = 0.9
    model_name: str | None = None
    emotion_state: dict = field(default_factory=dict)  # 8 类情绪 0~1
    pinned_emotion: dict | None = None                  # 手动钉住的情绪
    pinned_ratios: dict | None = None                   # 手动钉住的占比
    current_ratio: dict | None = None
    pressure: float = 0.0                               # 压力锅积压（默认关闭）
    summary: str = ""                                   # 跨会话记忆
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.character_id:
            self.character_id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = _now()
        self.updated_at = _now()
        self.current_ratio = dict(self.base_ratio)

    @property
    def is_balanced(self) -> bool:
        return True

    def to_dict(self) -> dict:
        return {
            "character_id": self.character_id,
            "name": self.name,
            "base_ratio": dict(self.base_ratio),
            "traits": [t.to_dict() for t in self.traits],
            "events": [e.to_dict() for e in self.events],
            "hard_rules": list(self.hard_rules),
            "soft_rules": list(self.soft_rules),
            "temperature": self.temperature,
            "model_name": self.model_name,
            "emotion_state": dict(self.emotion_state),
            "pinned_emotion": dict(self.pinned_emotion) if self.pinned_emotion else None,
            "pinned_ratios": dict(self.pinned_ratios) if self.pinned_ratios else None,
            "current_ratio": dict(self.current_ratio) if self.current_ratio else dict(self.base_ratio),
            "pressure": self.pressure,
            "summary": self.summary,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Character":
        c = cls(
            character_id=data.get("character_id", ""),
            name=data.get("name", "未命名角色"),
            base_ratio=dict(data.get("base_ratio", {"id": 33, "ego": 34, "superego": 33})),
            traits=[Trait.from_dict(t) for t in data.get("traits", [])],
            events=[StoryEvent.from_dict(e) for e in data.get("events", [])],
            hard_rules=list(data.get("hard_rules", []) or []),
            soft_rules=list(data.get("soft_rules", []) or []),
            temperature=float(data.get("temperature", 0.9)),
            model_name=data.get("model_name"),
            emotion_state=dict(data.get("emotion_state", {}) or {}),
            pinned_emotion=dict(data["pinned_emotion"]) if data.get("pinned_emotion") else None,
            pinned_ratios=dict(data["pinned_ratios"]) if data.get("pinned_ratios") else None,
            current_ratio=dict(data["current_ratio"]) if data.get("current_ratio") else None,
            pressure=float(data.get("pressure", 0.0) or 0.0),
            summary=data.get("summary", ""),
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


# ============================================================
# 四通道消息
# ============================================================

@dataclass
class StoryMessage:
    """一条对演记录。

    entry_type:
    - "narrator": 旁白/场景描写
    - "character": 角色四通道（思考/表情/动作/台词）
    - "director": 导演注入（剧情指令/突发事件）
    """
    speaker_name: str
    entry_type: str = "character"
    thinking: str = ""
    expression: str = ""
    action: str = ""
    speech: str = ""
    emotion: dict = field(default_factory=dict)
    round_number: int = 0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = _now()

    @property
    def content(self) -> str:
        if self.entry_type in ("narrator", "director"):
            return self.thinking or self.speech or ""
        return self.speech

    def to_dict(self) -> dict:
        return {
            "speaker_name": self.speaker_name,
            "entry_type": self.entry_type,
            "thinking": self.thinking,
            "expression": self.expression,
            "action": self.action,
            "speech": self.speech,
            "emotion": dict(self.emotion),
            "round_number": self.round_number,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StoryMessage":
        return cls(
            speaker_name=data.get("speaker_name", ""),
            entry_type=data.get("entry_type", "character"),
            thinking=data.get("thinking", ""),
            expression=data.get("expression", ""),
            action=data.get("action", ""),
            speech=data.get("speech", ""),
            emotion=dict(data.get("emotion", {}) or {}),
            round_number=int(data.get("round_number", 0) or 0),
            timestamp=data.get("timestamp", ""),
        )

    def format_script(self) -> str:
        """剧本文本：用于 LLM 上下文和导出。"""
        if self.entry_type == "narrator":
            return self.thinking or self.speech
        if self.entry_type == "director":
            return f"【导演】{self.thinking or self.speech}"
        parts = []
        if self.expression:
            parts.append(f"（{self.expression}）")
        if self.action:
            parts.append(self.action)
        if self.speech:
            parts.append(f"「{self.speech}」")
        if not parts:
            parts.append(self.speech)
        return f"{self.speaker_name}：{' '.join(parts)}"


# ============================================================
# 剧情会话
# ============================================================

@dataclass
class StorySession:
    """一场对演：场景 + 角色 + 剧本记录 + 生命周期。"""
    title: str
    scene: dict = field(default_factory=dict)  # location/time/background/mood/opening
    character_ids: list[str] = field(default_factory=list)
    narrator_enabled: bool = True
    max_rounds: int = 8
    session_id: str = ""
    status: str = "waiting"  # waiting | discussing | paused | ended
    transcript: list[StoryMessage] = field(default_factory=list)
    current_round: int = 0
    active_turn: dict | None = None
    created_at: str = ""
    ended_at: str | None = None

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"st-{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = _now()

    def scene_text(self) -> str:
        parts = []
        if self.scene.get("location"):
            parts.append(f"地点：{self.scene['location']}")
        if self.scene.get("time"):
            parts.append(f"时间：{self.scene['time']}")
        if self.scene.get("mood"):
            parts.append(f"气氛：{self.scene['mood']}")
        if self.scene.get("background"):
            parts.append(f"背景：{self.scene['background']}")
        if self.scene.get("opening"):
            parts.append(f"开场：{self.scene['opening']}")
        return "\n".join(parts)

    def begin_active_turn(self, speaker_name: str, entry_type: str = "character") -> None:
        self.active_turn = {
            "speaker_name": speaker_name,
            "entry_type": entry_type,
            "content": "",
        }

    def append_active_turn(self, content: str) -> None:
        if self.active_turn is not None:
            self.active_turn["content"] += content

    def end_active_turn(self) -> None:
        self.active_turn = None

    def get_summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "status": self.status,
            "scene": dict(self.scene),
            "character_ids": list(self.character_ids),
            "narrator_enabled": self.narrator_enabled,
            "current_round": self.current_round,
            "max_rounds": self.max_rounds,
            "transcript_count": len(self.transcript),
            "created_at": self.created_at,
            "ended_at": self.ended_at,
        }

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "session_type": "story",
            "title": self.title,
            "scene": dict(self.scene),
            "character_ids": list(self.character_ids),
            "narrator_enabled": self.narrator_enabled,
            "max_rounds": self.max_rounds,
            "status": self.status,
            "transcript": [m.to_dict() for m in self.transcript],
            "current_round": self.current_round,
            "active_turn": dict(self.active_turn) if self.active_turn else None,
            "created_at": self.created_at,
            "ended_at": self.ended_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StorySession":
        s = cls(
            title=data.get("title", "未命名故事"),
            scene=dict(data.get("scene", {}) or {}),
            character_ids=list(data.get("character_ids", []) or []),
            narrator_enabled=bool(data.get("narrator_enabled", True)),
            max_rounds=int(data.get("max_rounds", 8) or 8),
            session_id=data.get("session_id", ""),
            status=data.get("status", "ended"),
            transcript=[StoryMessage.from_dict(m) for m in data.get("transcript", [])],
            current_round=int(data.get("current_round", 0) or 0),
            active_turn=None,
            created_at=data.get("created_at", ""),
            ended_at=data.get("ended_at"),
        )
        s.active_turn = None
        return s

    def save(self) -> bool:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = SESSIONS_DIR / f"{self.session_id}.json"
        tmp_path = file_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(str(tmp_path), str(file_path))
            return True
        except (IOError, OSError) as e:
            logger.error(f"保存故事 {self.session_id} 失败: {e}")
            return False

    @classmethod
    def load(cls, session_id: str) -> "StorySession | None":
        file_path = SESSIONS_DIR / f"{session_id}.json"
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("session_type") != "story":
                return None
            return cls.from_dict(data)
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.error(f"加载故事 {session_id} 失败: {e}")
            return None

