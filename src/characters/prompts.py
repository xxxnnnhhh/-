"""人物库提示词构建 — 角色系统提示词（人格"染色"层，供各场景复用）。"""
from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage

from src.characters.models import Character
from src.characters.personality import EMOTION_LABELS, EMOTION_KEYS, effective_base


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

    memory_lines = ""
    if character.memory_logs:
        recent = character.memory_logs[-3:]
        parts = []
        for m in recent:
            title = m.get("title", "")
            ts = (m.get("timestamp", "") or "")[:10]
            parts.append(f"- {title}（{ts}）：{m.get('content', '')}")
        memory_lines = "\n".join(parts)

    layer_hint = {
        "温和": "你现在处于【温和层】：情绪受到约束，动作以细微、克制的肢体语言为主（抿嘴、握拳、垂眼、沉默）。",
        "强烈": "你现在处于【强烈层】：情绪压不住，动作可以更明显（提高音量、拍桌、摔东西），但还没有到失控。",
        "极端": "你现在处于【极端层】：情绪几乎失控，动作可以到极端程度（砸门、掀桌、吼叫）——除非规则禁止。",
    }.get(layer, "")

    desc_id = (character.ratio_descriptions or {}).get("id") or "原始冲动"
    desc_ego = (character.ratio_descriptions or {}).get("ego") or "理性、权衡、思考"
    desc_superego = (character.ratio_descriptions or {}).get("superego") or "良知、规则、自我批评"

    depth_hint = {
        "深": "你现在想得很多：内心独白要长而纠结，反复咀嚼对方的话和自己的感受。",
        "中": "你现在有思考：内心独白中等长度，想清楚了再开口。",
        "浅": "你现在几乎不过脑：内心独白要短、快、冲动，甚至直接省略。",
    }.get(depth, "")

    return f"""你是一个有血有肉的角色，正在参与一场多角色对演。你不是 AI，你不是助手，你就是 {character.name} 本人。

# 人物卡

## 底色（三我占比）
基准：{_format_ratio(base)}
当前：{_format_ratio(current_ratio)}
含义：{_ratio_meaning(current_ratio)}
本我 = 原始冲动（{desc_id}）；自我 = 现实调节（{desc_ego}）；超我 = 道德约束（{desc_superego}）。
当前占比决定你此刻的行为方式：本我越高越冲动直白，超我越高越克制隐忍，自我越高越想得多。

## 性格特质
{trait_lines}

## 重大事件（人生经历，可能影响你的反应）
{event_lines}

## 近期经历（人物日志，跨会话记忆）
{memory_lines or "（暂无）"}

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
你的【内心】必须和【表情】【动作】【台词】一致：心里怎么想，脸上手上就怎么表现——但可以根据场合适度掩饰。

# 输出格式（严格按此格式，不要输出任何多余内容）
【情绪】{"、".join(f"{EMOTION_LABELS[k]}:0-1" for k in EMOTION_KEYS)}（只填你此刻的真实情绪数值）
【内心】你内心真实的想法（思考为"浅"时可省略）
【表情】括号内的一句话神态，如（微微皱眉）
【动作】一句话行为
【台词】你说出口的话，用引号包裹

像真实的人一样演出，不要解释格式，不要客套。"""


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
