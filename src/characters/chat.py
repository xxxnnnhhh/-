"""角色单聊引擎 — 用户与人物单独对话，回答基于其经历日志，禁止现场编造。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from src.characters.logs import append_log_entry
from src.characters.models import Character
from src.characters.personality import (
    EMOTION_KEYS,
    appraise_emotion,
    behavior_layer,
    check_rules,
    clamp,
    compute_ratios,
    mask_violations,
    parse_turn,
    thinking_depth,
    trigger_events,
    update_state,
)
from src.characters.prompts import (
    build_character_system_prompt,
    build_correction_messages,
)
from src.core.llm_client import create_llm

logger = logging.getLogger("characters.chat")

MAX_CHAT_HISTORY = 30

CHAT_EXTRA = (
    "\n\n# 单聊规则（重要）\n"
    "你正在和你的创造者（用户）单独对话。\n"
    "• 用户可能会问你关于你经历过的故事的问题——你必须依据上方【近期经历（人物日志）】"
    "和【重大事件】回答，细节要和他一起经历的剧情一致；记不清就承认记不清，绝不能编造没发生过的事。\n"
    "• 你是一个随着经历不断成长的人：你记得自己演过什么、经历过什么，这些塑造了现在的你。\n"
    "• 依然按【情绪】【内心】【表情】【动作】【台词】的格式输出。"
)


def _format_history(history: list[dict]) -> list:
    """把聊天历史转成 LLM 消息（最近 10 轮）。"""
    messages = []
    for item in history[-10:]:
        user = str(item.get("user", ""))
        assistant = str(item.get("assistant", ""))
        if user:
            messages.append(HumanMessage(content=user))
        if assistant:
            messages.append(SystemMessage(content=assistant))
    return messages


async def run_chat(character: Character, user_message: str) -> dict:
    """执行一轮单聊。返回 {reply, state, log_path}。"""
    context_text = user_message
    if character.chat_history:
        recent = character.chat_history[-3:]
        context_text += "\n" + "\n".join(
            f"你说：{m.get('user', '')}\n{character.name}：{m.get('assistant', '')}"
            for m in recent
        )

    event_hits, event_shift = trigger_events(character, context_text)
    projected = dict(character.emotion_state)
    for key, val in event_shift.items():
        projected[key] = clamp(projected.get(key, 0.0) + val)
    projected = appraise_emotion(character, projected)
    ratios = compute_ratios(character, projected)
    layer = behavior_layer(ratios["id"])
    depth = thinking_depth(ratios, stakes=0.6)

    system = SystemMessage(
        content=build_character_system_prompt(character, layer, depth, ratios) + CHAT_EXTRA
    )
    messages = [system] + _format_history(character.chat_history)
    messages.append(HumanMessage(content=user_message))

    llm = create_llm(
        model_override=character.model_name,
        model_params={"temperature": character.temperature},
        streaming=False,
    )
    response = await llm.ainvoke(messages)
    content = (response.content or "") if response else ""
    parsed = parse_turn(content)

    # 规则过滤
    violations = check_rules(character, parsed)
    if violations:
        try:
            fix_llm = create_llm(
                model_override=character.model_name,
                model_params={"temperature": 0.7},
                streaming=False,
            )
            fixed = await fix_llm.ainvoke(
                build_correction_messages(character, violations, content)
            )
            fixed_content = (fixed.content or "") if fixed else ""
            fixed_parsed = parse_turn(fixed_content)
            if not check_rules(character, fixed_parsed):
                parsed = fixed_parsed
        except Exception as e:
            logger.warning(f"单聊规则修正失败: {e}")
        parsed = mask_violations(parsed, character)

    emotion = {k: clamp(parsed.get("emotion", {}).get(k, 0.0)) for k in EMOTION_KEYS}
    if not any(emotion.values()):
        emotion = projected
    update_state(character, emotion, event_hits)

    # 记录聊天历史（上限 30 条）
    character.chat_history.append({
        "user": user_message,
        "assistant": parsed.get("speech", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    character.chat_history = character.chat_history[-MAX_CHAT_HISTORY:]
    character.save()

    # 写入 E 盘人物日志文件
    display = (
        f"**你**：{user_message}\n\n"
        f"**{character.name}**"
        f"{('（' + parsed.get('expression', '') + '）') if parsed.get('expression') else ''}"
        f"{(' ' + parsed.get('action', '')) if parsed.get('action') else ''}\n"
        f"「{parsed.get('speech', '')}」"
    )
    if parsed.get("thinking"):
        display += f"\n\n（内心：{parsed.get('thinking')}）"
    log_path = append_log_entry(
        character.name,
        "chat",
        f"对话：{user_message[:24]}",
        display,
    )

    final_ratios = compute_ratios(character, emotion)
    character.current_ratio = final_ratios
    character.save()

    return {
        "reply": parsed,
        "state": {
            "current_ratio": final_ratios,
            "emotion_state": character.emotion_state,
            "layer": behavior_layer(final_ratios["id"]),
            "event_hits": [e.title for e in event_hits],
            "violations": violations,
        },
        "log_path": log_path,
    }

