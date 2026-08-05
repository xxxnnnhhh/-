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
from src.characters.websearch import web_search
from src.core.llm_client import create_llm

logger = logging.getLogger("characters.chat")

MAX_CHAT_HISTORY = 500          # 完整保留对话记录（上下文只取最近若干条）
MAX_HISTORY_ENTRY = 800  # 历史每条最多保留的字数，防止上下文膨胀
MAX_CONTINUATION = 4            # 长文输出最多续写次数

CHAT_EXTRA = (
    "\n\n# 单聊规则（重要）\n"
    "你正在和你的创造者（用户）单独对话。\n"
    "• 用户可能会问你关于你经历过的故事的问题——你必须依据上方【近期经历（人物日志）】"
    "和【重大事件】回答，细节要和他一起经历的剧情一致；记不清就承认记不清，绝不能编造没发生过的事。\n"
    "• 你是一个随着经历不断成长的人：你记得自己演过什么、经历过什么，这些塑造了现在的你。\n"
    "• 依然按【情绪】【内心】【表情】【动作】【台词】的格式输出。"
)

SEARCH_EXTRA = (
    "\n\n# 联网资料（可引用，但别当成亲身经历）\n"
    "{search_results}"
    "\n你可以引用上面的最新资料来回答，但依然保持你的语气、立场和人设；"
    "不要把搜索资料说成你自己亲身经历的事。"
)


def _format_history(history: list[dict]) -> list:
    """把聊天历史转成 LLM 消息（最近 10 轮）。"""
    messages = []
    for item in history[-10:]:
        user = str(item.get("user", ""))[:MAX_HISTORY_ENTRY]
        assistant = str(item.get("assistant", ""))[:MAX_HISTORY_ENTRY]
        if user:
            messages.append(HumanMessage(content=user))
        if assistant:
            messages.append(SystemMessage(content=assistant))
    return messages


async def run_chat(
    character: Character,
    user_message: str,
    search: bool = False,
) -> dict:
    """执行一轮单聊。返回 {reply, state, log_path}。"""
    context_text = user_message[:MAX_HISTORY_ENTRY]
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

    system_content = (
        build_character_system_prompt(character, layer, depth, ratios) + CHAT_EXTRA
    )
    if search:
        results = await web_search(user_message)
        if results:
            search_text = "\n".join(
                f"- {r['title']}：{r['snippet'][:300] or '（无摘要）'}（{r['url']}）"
                for r in results
            )
            system_content += SEARCH_EXTRA.format(search_results=search_text)
    system = SystemMessage(content=system_content)
    messages = [system] + _format_history(character.chat_history)
    messages.append(HumanMessage(content=user_message))

    llm = create_llm(
        model_override=character.model_name,
        model_params={"temperature": character.temperature},
        streaming=False,
        max_tokens=8192,  # 支持长文输出
    )
    # 长文输出：若被长度截断则自动续写，最多 MAX_CONTINUATION 次
    full_text = ""
    for _ in range(MAX_CONTINUATION):
        response = await llm.ainvoke(messages)
        chunk = (response.content or "") if response else ""
        full_text += chunk
        finish_reason = (
            (response.response_metadata or {}).get("finish_reason")
            if response else None
        )
        if finish_reason != "length" or not chunk:
            break
        messages = messages + [
            HumanMessage(
                content="（请继续，从刚才中断的地方接着写，不要重复已写内容。）"
            )
        ]
    content = full_text
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


def build_chat_document(character: Character) -> str:
    """把完整对话历史生成结构化 Markdown，供其他 AI 直接读取。"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()[:16].replace("T", " ")
    desc = character.ratio_descriptions or {}
    lines = [
        f"# 与 {character.name} 的对话记录",
        "",
        f"导出时间：{now}",
        "",
        "## 角色档案",
        (
            f"- 三我占比：本我 {character.base_ratio.get('id', 0)} / "
            f"自我 {character.base_ratio.get('ego', 0)} / "
            f"超我 {character.base_ratio.get('superego', 0)}"
        ),
        f"- 本我：{desc.get('id') or '（未填写）'}",
        f"- 自我：{desc.get('ego') or '（未填写）'}",
        f"- 超我：{desc.get('superego') or '（未填写）'}",
    ]
    if character.traits:
        lines.append("- 特质：" + "、".join(t.name for t in character.traits))
    if character.events:
        lines.append("- 重大事件：" + "；".join(e.title for e in character.events))
    lines.append("")
    lines.append("## 对话记录")
    lines.append("")
    for item in character.chat_history:
        ts = (item.get("timestamp") or "")[:16].replace("T", " ")
        user = str(item.get("user", ""))
        assistant = str(item.get("assistant", ""))
        lines.append(f"[{ts}] 用户：{user}")
        lines.append("")
        lines.append(f"[{ts}] {character.name}：「{assistant}」")
        lines.append("")
    return "\n".join(lines)


def export_chat_document(character: Character) -> dict:
    """导出聊天文档到 E 盘，返回 {markdown, path}。"""
    from src.characters.logs import LOG_DIR, _safe_name

    doc = build_chat_document(character)
    path = LOG_DIR / f"{_safe_name(character.name)}-对话记录.md"
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(doc, encoding="utf-8")
        return {"markdown": doc, "path": str(path)}
    except OSError as e:
        logger.error(f"导出对话文档失败 {path}: {e}")
        return {"markdown": doc, "path": ""}
