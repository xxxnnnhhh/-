"""故事机器提示词构建 — 场景/旁白/角色轮次（人物卡由人物库提供）。"""
from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage

from src.characters.prompts import (  # noqa: F401 (re-export)
    build_character_system_prompt,
    build_correction_messages,
)
from src.story.models import Character, StoryEvent, StoryMessage, StorySession


def format_transcript_tail(transcript: list[StoryMessage], tail: int = 10) -> str:
    """把最近的剧本记录格式化为 LLM 可见的上下文。"""
    if not transcript:
        return "（还没有发生任何对话，这是开场）"
    lines = []
    for m in transcript[-tail:]:
        if m.entry_type == "narrator":
            lines.append(f"【旁白】{m.thinking or m.speech}")
        elif m.entry_type == "director":
            lines.append(f"【导演】{m.thinking or m.speech}")
        else:
            lines.append(m.format_script())
    return "\n".join(lines)


def build_character_turn_messages(
    character: Character,
    session: StorySession,
    event_hits: list[StoryEvent],
    layer: str,
    depth: str,
    current_ratio: dict,
    other_names: list[str],
) -> list:
    """为某角色构建本轮发言的完整消息列表。"""
    system = SystemMessage(
        content=build_character_system_prompt(character, layer, depth, current_ratio)
    )

    event_note = ""
    if event_hits:
        titles = "、".join(e.title for e in event_hits)
        event_note = (
            f"\n\n⚠️ 刚才的场景触发了你的一段往事（{titles}），"
            "它会直接影响你此刻的情绪和态度——按你的人物设定自然流露，不要解释原因。"
        )

    scene = session.scene_text()
    tail = format_transcript_tail(session.transcript)
    user_text = (
        f"# 场景\n{scene}\n\n"
        f"# 剧情进展\n{tail}\n\n"
        f"# 本轮\n"
        f"轮到 {character.name} 发言。场上还有：{'、'.join(other_names)}。"
        f"{event_note}\n\n"
        f"请按【情绪】【内心】【表情】【动作】【台词】的格式输出 {character.name} 这一轮的表现。"
    )
    return [system, HumanMessage(content=user_text)]


NARRATOR_SYSTEM_PROMPT = """你是一位小说旁白叙述者，负责为一场双人角色对演写场景描写。
文风：简洁、有画面感、文学性，像小说正文，不要解释、不要评价角色、不要替角色说话。
长度：2-4 句话。避免重复已经出现的描写。"""


def build_narrator_messages(session: StorySession) -> list:
    scene = session.scene_text()
    tail = format_transcript_tail(session.transcript, tail=4)
    if session.current_round == 0:
        instruction = "这是开场：请描写场景本身（地点、光线、氛围），并为两个角色的出场做铺垫。"
    else:
        instruction = "这是新一轮：请用一个简短的环境/氛围镜头衔接上一段剧情。"
    user_text = (
        f"# 场景设定\n{scene}\n\n# 最近的剧情\n{tail}\n\n{instruction}"
    )
    return [SystemMessage(content=NARRATOR_SYSTEM_PROMPT), HumanMessage(content=user_text)]

