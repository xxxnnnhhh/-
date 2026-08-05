"""故事机器核心数据模型。

角色模型（Character/Trait/StoryEvent）由共享的人物库提供：
`from src.characters.models import Character, Trait, StoryEvent`（此处再导出）。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.characters.models import Character, Trait, StoryEvent  # noqa: F401 (re-export)
from src.config import SESSIONS_DIR

logger = logging.getLogger("story")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

