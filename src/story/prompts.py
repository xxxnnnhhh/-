"""故事机器提示词构建 — 人格"染色"的关键层。

原则：你的规则（硬/软） > 底色（三我占比） > 特质 > 情绪 > 输出格式。
"""
from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage

from src.story.models import Character, StoryEvent, StoryMessage, StorySession
from src.story.personality import (
    EMOTION_LABELS,
    EMOTION_KEYS,
    effective_base,
)


def _format_emotion_state(character: Character) -> str:
    parts = []
    for key in EMOTION_KEYS:
        val = character.emotion_state.get(key, 0.0)
        if val > 0.05:
            parts.append(f"{EMOTION_LABELS[key]} {round(val, 2)}")
    if not parts:
        return "平静"
    return "、".join(parts)


def _format_ratio(ratio: dict) -> str:
    return (
        f"本我 {ratio.get('id', 0)} / 自我 {ratio.get('ego', 0)} / "
        f"超我 {ratio.get('superego', 0)}"
    )


def _ratio_meaning(ratio: dict) -> str:
    meaning = []
    if ratio.get("id", 0) >= 50:
        meaning.append("本我主导：冲动、直率、容易上头，行动先于思考")
    if ratio.get("ego", 0) >= 50:
        meaning.append("自我主导：理性、克制、权衡利弊，想得多")
    if ratio.get("superego", 0) >= 50:
        meaning.append("超我主导：自律、守规则、容易自我批评")
    if not meaning:
        meaning.append("三者相对平衡：多数时候正常，但情绪上来时也会波动")
    return "；".join(meaning)


def build_character_system_prompt(
    character: Character,
    layer: str,
    depth: str,
    current_ratio: dict,
) -> str:
    """角色系统提示词：人物卡 + 规则 + 输出格式。"""
    base = effective_base(character)

    trait_lines = "\n".join(f"- {t.name}" for t in character.traits) or "- 无"
    event_lines = "\n".join(
        f"- {e.title}：{e.description or '（未填写描述）'}"
        f"（触发词：{'、'.join(e.triggers) or '无'}）"
        for e in character.events
    ) or "- 无"
    hard_lines = "\n".join(f"- {r}" for r in character.hard_rules) or "- 无"
    soft_lines = "\n".join(f"- {r}" for r in character.soft_rules) or "- 无"

    layer_hint = {
        "温和": "你现在处于【温和层】：情绪受到约束，动作以细微、克制的肢体语言为主（抿嘴、握拳、垂眼、沉默）。",
        "强烈": "你现在处于【强烈层】：情绪压不住，动作可以更明显（提高音量、拍桌、摔东西），但还没有到失控。",
        "极端": "你现在处于【极端层】：情绪几乎失控，动作可以到极端程度（砸门、掀桌、吼叫）——除非规则禁止。",
    }.get(layer, "")

    depth_hint = {
        "深": "你现在想得很多：内心独白要长而纠结，反复咀嚼对方的话和自己的感受。",
        "中": "你现在有思考：内心独白中等长度，想清楚了再开口。",
        "浅": "你现在几乎不过脑：内心独白要短、快、冲动，甚至直接省略。",
    }.get(depth, "")

    return f"""你是一个有血有肉的小说角色，正在参与一场"双人对演"的写作演出。你不是 AI，你不是助手，你就是 {character.name} 本人。

# 人物卡

## 底色（三我占比）
基准：{_format_ratio(base)}
当前：{_format_ratio(current_ratio)}
含义：{_ratio_meaning(current_ratio)}
本我 = 原始冲动（想说什么就说什么的欲望）；自我 = 现实调节（理性、权衡、思考）；超我 = 道德约束（良知、规则、自我批评）。
当前占比决定你此刻的行为方式：本我越高越冲动直白，超我越高越克制隐忍，自我越高越想得多。

## 性格特质
{trait_lines}

## 重大事件（人生经历，可能影响你的反应）
{event_lines}

## 情绪状态（前一轮的余温）
{_format_emotion_state(character)}

# 规则（绝对不可违反，比一切都高）
## 硬规则（违反即出戏）
{hard_lines}
## 软规则（风格要求）
{soft_lines}
• 绝不说"作为AI/作为模型/希望对你有帮助"这类话
• 回复长短自然随意：有时一个字，有时一大段，不要每次都三段式
• 说人话，口语化，像真实对话，禁止列点、禁止"首先/其次/最后"

# 表演要求
{layer_hint}
{depth_hint}
你的【内心】必须和【表情】【动作】【台词】一致：心里怎么想，脸上手上就怎么表现——但可以根据场合适度掩饰（心里骂人，脸上微笑）。

# 输出格式（严格按此格式，不要输出任何多余内容）
【情绪】{"、".join(f"{EMOTION_LABELS[k]}:0-1" for k in EMOTION_KEYS)}（只填你此刻的真实情绪数值）
【内心】你内心真实的想法（按思考深度决定长短；思考为"浅"时可以省略这行）
【表情】括号内的一句话神态，如（微微皱眉）
【动作】一句话行为，如（放下杯子，指尖在桌沿敲了两下）
【台词】你说出口的话，用引号包裹

每一行都要像小说演出，不要解释格式，不要客套。"""


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


def build_correction_messages(
    character: Character,
    violations: list[str],
    original: str,
) -> list:
    system = SystemMessage(
        content=(
            "你是角色对演的规则修正器。刚才角色的一段表演违反了硬规则，"
            "请用同一角色的人设重写违规部分，保持原意和风格，只修正违规表达。"
            f"\n硬规则：{'；'.join(character.hard_rules) or '无'}"
            "\n输出格式与角色表演格式一致（【表情】【动作】【台词】，可含【内心】）。"
        )
    )
    user = HumanMessage(
        content=(
            f"违规原因：{'；'.join(violations)}\n\n原表演：\n{original}\n\n"
            "请重写为合规版本（保持人物性格）。"
        )
    )
    return [system, user]

