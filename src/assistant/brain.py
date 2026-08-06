"""书架总大脑核心逻辑。

总大脑 = 一本作品的 AI 助手：
- 对话时自动带上这本书的世界观 / 角色 / 大纲 / 章节状态 / 演绎记录 / 挂载的 Skills；
- 能"提案动作"（如改写章节正文、指挥流水线），由用户在界面确认后执行；
- 执行写入前自动留历史版本。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONTEXT_LIMITS = {
    "world_foundation": 8000,
    "outline": 4000,
    "theater": 3000,
}


def _read_first(path: Path, limit: int) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
        return text[:limit]
    except Exception:
        return ""


def _character_lines(characters: list[dict]) -> str:
    lines = []
    for c in characters:
        name = c.get("name", "未命名")
        types = "、".join(c.get("types") or []) or "通用"
        ratio = c.get("base_ratio") or {}
        ratio_txt = (
            f"本我{ratio.get('id', 0)}%/自我{ratio.get('ego', 0)}%/超我{ratio.get('superego', 0)}%"
            if ratio
            else "未设置"
        )
        stats = "、".join(f"{k}{v}" for k, v in (c.get("stats") or {}).items())
        traits = "、".join(t.get("name", "") for t in (c.get("traits") or []) if t.get("name")) or "无"
        eq = "、".join(e.get("name", "") for e in (c.get("equipment") or [])) or "无"
        skills = "、".join(c.get("skill_ids") or []) or "无"
        lines.append(
            f"- {name}（{types}）三我占比 {ratio_txt}；特质：{traits}；五维：{stats}；装备：{eq}；写作风格：{skills}"
        )
    return "\n".join(lines) or "（尚未关联角色）"


def build_context(project) -> str:
    """组装一本书的完整上下文（世界观/角色/大纲/章节/演绎/Skills）。"""
    from ..theater.models import TheaterSession
    from ..novel_pipeline.models import zero_pad_chapter

    ws = Path(project.workspace)
    world_foundation = _read_first(ws / "meta" / "world_foundation.md", _CONTEXT_LIMITS["world_foundation"])
    volume_outline = _read_first(ws / "outline" / "volume_outline.md", _CONTEXT_LIMITS["outline"])
    near_term = _read_first(ws / "outline" / "near_term_outline.md", _CONTEXT_LIMITS["outline"])

    # 角色
    characters: list[dict] = []
    if project.character_ids:
        try:
            from src.characters.manager import get_character_manager
            mgr = get_character_manager()
            for cid in project.character_ids:
                c = mgr.get(cid)
                if c:
                    characters.append(c.to_dict())
        except Exception:
            logger.exception("读取角色失败")

    # 章节状态
    chapters_txt = []
    for ch in project.chapters:
        ch_num = zero_pad_chapter(ch)
        md = ws / "story" / ch_num / "chapter.md"
        if md.is_file():
            text = md.read_text(encoding="utf-8")
            chapters_txt.append(
                f"- 第{int(ch)}章：已生成（{len(text)}字）"
                + (f"\n  开头：{text[:120].strip()}" if text.strip() else "")
            )
        else:
            chapters_txt.append(f"- 第{int(ch)}章：待生成")

    # 演绎记录
    theater_txt = []
    for sid in project.theater_session_ids[-5:]:
        s = TheaterSession.load(sid)
        if s:
            tail = "；".join(str(x) for x in (s.record or [])[-3:])
            theater_txt.append(f"- 《{s.title}》（{'讨论' if s.mode == 'discuss' else '演绎'}）：{tail[:400]}")

    # 挂载的 Skills
    skills_section = ""
    if project.skill_ids:
        try:
            from src.skills.loader import SkillLoader
            from src.config import SKILLS_DIR
            loader = SkillLoader(SKILLS_DIR)
            loaded = {s.id: s for s in loader.load_all()}
            active = [loaded[sid] for sid in project.skill_ids if sid in loaded and loaded[sid].enabled]
            if active:
                parts = ["# 本书挂载的写作风格 Skills", ""]
                for s in active:
                    parts.append(f"## {s.name} (`{s.id}`)")
                    parts.append(s.content)
                    parts.append("")
                skills_section = "\n".join(parts)
        except Exception:
            logger.exception("读取 Skills 失败")

    ctx = [
        f"## 作品《{project.name}》",
        f"类型：{project.genre or '未设置'}　语言：{project.language}",
        f"创意：{project.premise or '（无）'}",
        "",
        "## 世界观",
        world_foundation or "（尚未生成）",
        "",
        "## 角色",
        _character_lines(characters),
        "",
        "## 卷纲 / 近纲",
        volume_outline or "（尚未生成）",
        "",
        near_term or "",
        "",
        "## 章节状态",
        "\n".join(chapters_txt) or "（暂无章节规划）",
        "",
        "## 近期演绎记录",
        "\n".join(theater_txt) or "（暂无演绎记录）",
        "",
        skills_section,
    ]
    return "\n".join(ctx).strip()


def _parse_assistant_output(text: str) -> dict:
    """从 LLM 输出解析 {reply, action}，兼容 markdown 代码块包裹。"""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试截取第一个 {...} 块
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not m:
            return {"reply": cleaned, "action": None}
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"reply": cleaned, "action": None}
    if not isinstance(data, dict):
        return {"reply": cleaned, "action": None}
    reply = str(data.get("reply") or data.get("message") or "").strip()
    action = data.get("action")
    if action is None:
        return {"reply": reply or cleaned, "action": None}
    if not isinstance(action, dict):
        return {"reply": reply or cleaned, "action": None}
    return {"reply": reply or cleaned, "action": action}


SYSTEM_TEMPLATE = """你是「{book}」这本书的总大脑——一个能通读全书、指挥创作的写作助手。
你可以回答关于这本书的任何问题（世界观、角色、大纲、章节、演绎记录），也可以根据要求生成或改写内容。

==== 本书上下文 ====
{context}

==== 你的能力 ====
1. 纯问答：直接回答，不需要操作。
2. 生成/改写章节正文：当用户要求"写第N章""重写第N章""把第N章改成..."时，完整生成该章正文并提案写入。
3. 指挥流水线：当用户要求"生成世界观/角色/大纲/跑流水线/写某一步"时，可以提案运行对应步骤。

==== 输出协议（严格遵守，任何情况下都只输出一个 JSON 对象） ====
{"reply": "给用户的话（中文，简短说明你做了什么或问了什么）", "action": null}

当用户要求"写第N章 / 重写第N章 / 把第N章改成..."时，正文必须放进 action.arguments.body（完整整章，不是片段），reply 只写简短说明：
{"reply": "已按古风文笔写好第1章，请确认后写入", "action": {"operation": "chapter_body_update", "arguments": {"chapter_number": "1", "body": "……完整章节正文……", "reason": "用户要求写第1章"}}}

当用户要求"生成世界观 / 角色 / 大纲 / 跑流水线 / 生成第N章（用流水线）"时：
{"reply": "已准备好启动对应步骤，请确认", "action": {"operation": "run_step", "arguments": {"step_key": "build"}}}

可用 step_key：build（世界观构建）、character（角色创建）、story-plan（故事规划）、outline（卷纲近纲）、
chapter-0001-mvp（第1章生产）、chapter-0001-post-hoc（后验）、chapter-0001-polish（润色），依此类推。

注意：正文内容不得出现在 reply 里，只出现在 action.arguments.body；回复必须符合挂载的写作风格 Skills。
"""


async def chat(project, messages: list[dict], model_override: str | None = None) -> dict:
    """与总大脑对话。返回 {reply, action}。"""
    from src.core.llm_client import create_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    context = build_context(project)
    system = (
        SYSTEM_TEMPLATE
        .replace("{book}", project.name)
        .replace("{context}", context)
    )

    model = model_override or "zhipu:glm-4.6"
    try:
        llm = create_llm(streaming=False, model_override=model)
    except Exception:
        logger.exception("使用 glm-4.6 失败，回退默认模型")
        llm = create_llm(streaming=False)
    history = []
    for m in (messages or [])[-20:]:
        role = m.get("role")
        content = m.get("content", "")
        if not content:
            continue
        if role == "user":
            history.append(HumanMessage(content=str(content)))
        elif role == "assistant":
            history.append(SystemMessage(content=str(content)))
    if not history:
        history.append(HumanMessage(content="你好，介绍一下这本书现在的状态。"))

    try:
        resp = await llm.ainvoke([SystemMessage(content=system), *history])
        text = str(resp.content or "")
    except Exception as exc:
        logger.exception("总大脑对话失败")
        return {"reply": f"（调用模型失败：{exc}）", "action": None}
    parsed = _parse_assistant_output(text)
    if parsed.get("action") is None:
        fallback = _maybe_wrap_write_intent(parsed.get("reply", ""), messages)
        if fallback is not None:
            parsed["action"] = fallback
    return parsed


_WRITE_INTENT_RE = re.compile(r"(写|重写|改写|生成|续写).{0,12}?(第\s*(\d+)\s*章|本章|正文|章节)")


def _maybe_wrap_write_intent(reply: str, messages: list[dict]) -> dict | None:
    """兜底：用户要求写/改章节但模型没走协议时，把回复正文包装成写入动作。"""
    last_user = next((m.get("content", "") for m in reversed(messages or []) if m.get("role") == "user"), "")
    m = _WRITE_INTENT_RE.search(last_user)
    if not m:
        return None
    chapter = m.group(2) if m.group(2) else "1"
    body = reply
    # 去掉模型加的引导行
    lines = [ln for ln in body.split("\n") if "以下是" not in ln and ln.strip() != "---"]
    body = "\n".join(lines).strip()
    if not body:
        return None
    return {
        "operation": "chapter_body_update",
        "arguments": {
            "chapter_number": chapter,
            "body": body,
            "reason": "用户要求写/改章节（自动包装）",
        },
    }


def _chapter_dir(project, chapter_number: str) -> Path:
    return Path(project.workspace) / "story" / chapter_number


def execute_chapter_body_update(project, arguments: dict) -> dict:
    """执行章节正文写入（写入前自动备份历史版本）。"""
    from ..novel_pipeline.models import zero_pad_chapter

    ch_num = zero_pad_chapter(arguments.get("chapter_number", "1"))
    body = str(arguments.get("body", "")).strip()
    reason = str(arguments.get("reason", "")).strip() or "总大脑改写"
    if not body:
        return {"success": False, "message": "正文为空"}
    chapter_dir = _chapter_dir(project, ch_num)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    chapter_md = chapter_dir / "chapter.md"

    version_info = None
    if chapter_md.exists():
        ts = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
        versions_dir = chapter_dir / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        old = chapter_md.read_text(encoding="utf-8")
        version_path = versions_dir / f"v{ts}.md"
        version_path.write_text(old, encoding="utf-8")
        version_info = {
            "path": str(version_path),
            "old_word_count": len(old),
            "reason": reason,
        }

    chapter_md.write_text(body + "\n", encoding="utf-8")
    return {
        "success": True,
        "message": f"第{int(ch_num)}章正文已写入（{len(body)}字）",
        "chapter_number": ch_num,
        "word_count": len(body),
        "version": version_info,
    }


def execute_action(project, operation: str, arguments: dict) -> dict:
    """执行确认后的动作。"""
    op = (operation or "").strip()
    args = arguments or {}
    if op == "chapter_body_update":
        return execute_chapter_body_update(project, args)
    if op == "run_step":
        from src.novel_pipeline.runner import NovelPipelineRunner
        step_key = str(args.get("step_key", "")).strip()
        if not step_key:
            return {"success": False, "message": "缺少 step_key"}
        # 复用全局 runner（路由层持有）；这里直接创建临时 runner 不共享，改为由路由层执行
        return {"success": False, "message": "run_step 请通过流水线接口执行", "step_key": step_key}
    return {"success": False, "message": f"未知动作: {op}"}
