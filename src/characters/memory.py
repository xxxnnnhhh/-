"""人物日志 — 跨会话记忆：会话结束后为角色生成经历记录，供后续读取。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from src.characters.models import Character
from src.core.llm_client import create_llm

logger = logging.getLogger("characters.memory")

MAX_MEMORY_LOGS = 20

MEMORY_SYSTEM_PROMPT = """你是一名小说编辑，负责为角色撰写"人物日志"。
用简洁有张力的文字记录这一场戏里该角色经历了什么：
- 发生了什么事、对方是谁
- 该角色的情绪变化和内心反应
- 关系发生了什么变化（更亲近/更疏远/信任破裂等）
- 他此刻的立场和未解的心结
长度 80-150 字，像角色自己的日记或档案记录，第三人称或第一人称均可。
不要评价剧情好坏，只记录事实和内心。"""


def _safe_truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "……"


async def generate_character_log(
    character: Character,
    session_title: str,
    transcript_text: str,
    session_type: str = "story",
) -> str:
    """用 LLM 为该角色生成一场戏的人物日志。失败时返回空串。"""
    if not transcript_text.strip():
        return ""
    try:
        llm = create_llm(
            model_override=character.model_name,
            model_params={"temperature": 0.6},
            streaming=False,
        )
        user_text = (
            f"角色：{character.name}（三我占比 本我{character.base_ratio.get('id', 0)} / "
            f"自我{character.base_ratio.get('ego', 0)} / 超我{character.base_ratio.get('superego', 0)}）\n"
            f"场景/议题：{session_title}\n"
            f"对演记录：\n{_safe_truncate(transcript_text, 4000)}\n\n"
            "请为这个角色写人物日志。"
        )
        response = await llm.ainvoke(
            [SystemMessage(content=MEMORY_SYSTEM_PROMPT), HumanMessage(content=user_text)]
        )
        content = (response.content or "").strip() if response else ""
        return content
    except Exception as e:
        logger.warning(f"生成角色 {character.name} 的人物日志失败: {e}")
        return ""


def append_memory(
    character: Character,
    content: str,
    session_id: str,
    session_type: str,
    title: str,
) -> None:
    """把一条人物日志写入角色的记忆并保存。"""
    entry = {
        "type": session_type,
        "session_id": session_id,
        "title": title,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    character.memory_logs.append(entry)
    character.memory_logs = character.memory_logs[-MAX_MEMORY_LOGS:]
    character.updated_at = datetime.now(timezone.utc).isoformat()
    character.save()


def clear_memory(character: Character) -> None:
    character.memory_logs = []
    character.updated_at = datetime.now(timezone.utc).isoformat()
    character.save()

