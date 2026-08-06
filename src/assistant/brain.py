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

WORKFLOW_ORDER = [
    ("bishu-novel-build", "世界观构建"),
    ("bishu-novel-character", "角色创建"),
    ("bishu-novel-story-plan", "故事宏观规划"),
    ("bishu-novel-outline", "卷纲近纲规划"),
    ("bishu-novel-mvp", "章节生产"),
    ("bishu-novel-post-hoc", "章节后验"),
    ("bishu-novel-polish", "章节润色"),
]


def _workflow_structure_summary() -> str:
    """列出 7 个可调配工作流的节点清单（让大脑知道能改什么）。"""
    from src.config import WORKFLOWS_DIR
    lines = []
    for wf_id, wf_name in WORKFLOW_ORDER:
        def_file = WORKFLOWS_DIR / wf_id / "definition.json"
        if not def_file.exists():
            continue
        try:
            import json as _json
            definition = _json.loads(def_file.read_text(encoding="utf-8"))
            nodes = definition.get("nodes", [])
            node_txt = "、".join(
                f"{n.get('id','?')}({n.get('label', n.get('id','?'))})" for n in nodes
            )
            lines.append(f"- {wf_name}（{wf_id}，{len(nodes)}节点）：{node_txt}")
        except Exception:
            continue
    return "\n".join(lines)


def describe_workflows() -> str:
    """返回 7 个工作流的详细结构（节点/类型/关键任务）。"""
    from src.config import WORKFLOWS_DIR
    lines = []
    for wf_id, wf_name in WORKFLOW_ORDER:
        def_file = WORKFLOWS_DIR / wf_id / "definition.json"
        if not def_file.exists():
            lines.append(f"- {wf_name}（{wf_id}）：定义文件不存在")
            continue
        try:
            import json as _json
            definition = _json.loads(def_file.read_text(encoding="utf-8"))
            nodes = definition.get("nodes", [])
            parts = []
            for n in nodes:
                nid = n.get("id", "?")
                label = n.get("label", nid)
                ntype = n.get("node_type", "agent")
                snippet = ""
                fm = (n.get("first_message") or "").strip()
                if fm:
                    snippet = "｜" + fm[:50].replace("\n", " ")
                parts.append(f"{nid}（{label}·{ntype}{snippet}）")
            lines.append(f"## {wf_name}（{wf_id}）")
            lines.append("\n".join(parts))
        except Exception:
            continue
    return "\n\n".join(lines)


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

    # 最近错误（供诊断）
    error_lines = []
    if project.error:
        error_lines.append(f"- 项目级错误：{project.error[:600]}")
    for step in project.steps:
        if step.status == "failed" and step.error:
            error_lines.append(f"- 步骤[{step.label}]：{step.error[:600]}")
    errors_section = "\n".join(error_lines) or "（当前无失败）"

    # 工作流结构（可调配清单）
    workflow_summary = _workflow_structure_summary()

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
        "## 最近错误",
        errors_section,
        "",
        "## 可调配工作流（节点清单）",
        workflow_summary or "（工作流不可读）",
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
            mixed = _extract_action_from_mixed(cleaned)
            if mixed is not None:
                reply = _strip_action_text(cleaned)
                return {"reply": reply or "（已识别动作）", "action": mixed}
            return {"reply": cleaned, "action": None}
    if not isinstance(data, dict):
        mixed = _extract_action_from_mixed(cleaned)
        if mixed is not None:
            return {"reply": _strip_action_text(cleaned) or "（已识别动作）", "action": mixed}
        return {"reply": cleaned, "action": None}
    reply = str(data.get("reply") or data.get("message") or "").strip()
    action = data.get("action")
    if action is None:
        mixed = _extract_action_from_mixed(cleaned)
        if mixed is not None:
            return {"reply": reply or _strip_action_text(cleaned) or "（已识别动作）", "action": mixed}
        return {"reply": reply or cleaned, "action": None}
    if not isinstance(action, dict):
        return {"reply": reply or cleaned, "action": None}
    return {"reply": reply or cleaned, "action": action}


_ACTION_JSON_RE = re.compile(r'\{[^{}]*"operation"\s*:\s*"[a-z_]+"[^{}]*\}')
_KNOWN_OPS = ("run_pipeline", "describe_workflows", "run_step", "chapter_body_update", "workflow_update_node")


def _extract_action_from_mixed(text: str) -> dict | None:
    """从"回复+JSON 混杂"的输出里提取动作（弱模型兜底）。"""
    m = _ACTION_JSON_RE.search(text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict) and data.get("operation"):
                return data
        except json.JSONDecodeError:
            pass
    # 裸操作名 + 后面的 JSON 参数（run_step {"step_key": "build"}）
    op = re.search(r'"operation"\s*[:：=]\s*"?([a-z_]+)"?', text)
    op_name = op.group(1) if op else None
    if op_name is None:
        for known in _KNOWN_OPS:
            if re.search(r"(?<![A-Za-z_])" + known + r"(?![A-Za-z_])", text):
                op_name = known
                break
    if op_name:
        args: dict = {}
        rest = text[text.find(op_name):]
        jm = re.search(r"\{.*\}", rest, re.DOTALL)
        if jm:
            try:
                parsed = json.loads(jm.group(0))
                if isinstance(parsed, dict):
                    args = parsed
            except json.JSONDecodeError:
                pass
        if not args:
            for key, pattern in (
                ("step_key", r'"step_key"\s*[:：]\s*"([^"]+)"'),
                ("chapter_number", r'"chapter_number"\s*[:：]\s*"?(\d+)"?'),
                ("workflow_id", r'"workflow_id"\s*[:：]\s*"([^"]+)"'),
                ("node_id", r'"node_id"\s*[:：]\s*"([^"]+)"'),
                ("field", r'"field"\s*[:：]\s*"([^"]+)"'),
                ("new_value", r'"new_value"\s*[:：]\s*"([^"]*)"'),
                ("body", r'"body"\s*[:：]\s*"([^"]*)"'),
            ):
                km = re.search(pattern, rest)
                if km:
                    args[key] = km.group(1)
        return {"operation": op_name, "arguments": args}
    return None


def _strip_action_text(text: str) -> str:
    """去掉回复里夹带的 JSON/动作残片，保留可读文字。"""
    cleaned = _ACTION_JSON_RE.sub("", text)
    cleaned = re.sub(
        r"\b(?:run_step|chapter_body_update|workflow_update_node|describe_workflows|run_pipeline)\b\s*[：:（(]?[^。\n]*",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\{[^{}]*\}", "", cleaned)
    cleaned = re.sub(r"\s*\n\s*", "\n", cleaned).strip()
    return cleaned


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

当用户要求"把整个流水线串起来跑 / 连跑全部 / 一口气生成"时：
{"reply": "已准备好从头连跑整条流水线（世界观→角色→故事→卷纲→逐章生产/后验/润色），请确认", "action": {"operation": "run_pipeline", "arguments": {"reset": true}}}

当用户要求"描述 / 介绍 / 看看有哪些工作流 / 各节点是干嘛的"时，直接输出纯回复即可，不需要动作；若一定要用动作，用 describe_workflows：
{"reply": "这就把 7 个工作流的结构读出来给你看，请确认", "action": {"operation": "describe_workflows", "arguments": {}}}

当用户要求"调整/修改工作流里的某个节点"（改提示词、参数、标签）时，你必须引用上面"可调配工作流"里的真实节点 ID：
{"reply": "准备把大纲导演的提示词改为更关注伏笔，请确认", "action": {"operation": "workflow_update_node", "arguments": {"workflow_id": "bishu-novel-mvp", "node_id": "agent_od", "field": "first_message", "new_value": "……新的完整提示词……", "reason": "用户要求加强伏笔关注"}}}
允许修改的 field：first_message（给 AI 的任务指令）、system_prompt_template（补充规则）、label（节点名称）、model_override（模型覆盖，格式 供应商:模型 或留空）。

你只能使用以下操作：chapter_body_update / run_step / run_pipeline / workflow_update_node / describe_workflows。除此之外一律用纯回复，不要发明新操作。

可用 step_key：build（世界观构建）、character（角色创建）、story-plan（故事规划）、outline（卷纲近纲）、
chapter-0001-mvp（第1章生产）、chapter-0001-post-hoc（后验）、chapter-0001-polish（润色），依此类推。

注意：章节正文只出现在 action.arguments.body；回复必须符合挂载的写作风格 Skills；修改工作流前先确认节点真实存在。
重要：你的 reply 里禁止出现任何 JSON、大括号、操作名（如 run_step / chapter_body_update）——它们只能放在 action 字段里。
"""


async def chat(project, messages: list[dict], model_override: str | None = None) -> dict:
    """与总大脑对话。返回 {reply, action}。"""
    from src.core.llm_client import create_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    if not getattr(project, "assistant_enabled", True):
        return {"reply": "（总大脑 AI 已关闭：在助手页顶部打开「接入 AI」开关即可。）", "action": None}

    context = build_context(project)
    system = (
        SYSTEM_TEMPLATE
        .replace("{book}", project.name)
        .replace("{context}", context)
    )

    model = model_override or getattr(project, "assistant_model", "") or "zhipu:glm-4.6"
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


DIAGNOSE_TEMPLATE = """你是「{book}」这本书的总大脑，正在做失败诊断。
下面这本书的流水线/工作流刚刚失败了。请：
1. 用中文说明失败原因（结合上下文里的「最近错误」和工作流节点）；
2. 给出修复建议，可以是一个或多个动作：
   - workflow_update_node：修改某节点提示词/参数/标签后重跑；
   - run_step：直接重跑某个步骤（如失败步骤本身）。

只输出一个 JSON 对象：
{{"diagnosis": "失败原因与修复思路（中文，300字内）", "actions": [{{"operation": "workflow_update_node", "arguments": {{"workflow_id": "...", "node_id": "...", "field": "first_message", "new_value": "...", "reason": "..."}}, "explain": "为什么要这样改"}}]}}
没有需要执行的动作时 actions 为空数组。

==== 本书上下文 ====
{context}
"""


def _parse_diagnose_output(text: str) -> dict:
    """解析诊断输出：{diagnosis, actions}。"""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not m:
            return {"diagnosis": cleaned, "actions": []}
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {"diagnosis": cleaned, "actions": []}
    if not isinstance(data, dict):
        return {"diagnosis": cleaned, "actions": []}
    diagnosis = str(
        data.get("diagnosis") or data.get("reply") or data.get("message") or ""
    ).strip()
    actions = data.get("actions") or []
    if isinstance(actions, dict):
        actions = [actions]
    if not actions and data.get("action"):
        actions = [data["action"]]
    if not isinstance(actions, list):
        actions = []
    return {"diagnosis": diagnosis or cleaned, "actions": actions}


async def diagnose(project, model_override: str | None = None) -> dict:
    """流水线失败后自动诊断，返回 {diagnosis, actions}。"""
    from src.core.llm_client import create_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    if not getattr(project, "assistant_enabled", True):
        return {
            "diagnosis": "（总大脑 AI 已关闭，无法自动诊断。可在助手页开启。）",
            "actions": [],
        }
    context = build_context(project)
    system = (
        DIAGNOSE_TEMPLATE
        .replace("{book}", project.name)
        .replace("{context}", context)
    )
    model = model_override or getattr(project, "assistant_model", "") or "zhipu:glm-4.6"
    try:
        llm = create_llm(streaming=False, model_override=model)
    except Exception:
        llm = create_llm(streaming=False)
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content="请诊断当前失败并给出修复建议。"),
        ])
        text = str(resp.content or "")
    except Exception as exc:
        logger.exception("总大脑诊断失败")
        return {"diagnosis": f"（诊断调用失败：{exc}）", "actions": []}
    parsed = _parse_diagnose_output(text)
    return {"diagnosis": parsed["diagnosis"] or "（模型未给出诊断）", "actions": parsed["actions"]}


_NODE_EDIT_FIELDS = {"first_message", "system_prompt_template", "label", "model_override"}


def apply_workflow_node_update(manager, arguments: dict) -> dict:
    """修改工作流某节点的提示词/参数/标签（读取→打补丁→校验→保存）。"""
    workflow_id = str(arguments.get("workflow_id", "")).strip()
    node_id = str(arguments.get("node_id", "")).strip()
    field = str(arguments.get("field", "")).strip()
    new_value = arguments.get("new_value")
    reason = str(arguments.get("reason", "")).strip()
    if not workflow_id or not node_id or not field:
        return {"success": False, "message": "缺少 workflow_id / node_id / field"}

    # node_params.<key> 形式允许改脚本参数
    node_params_key = None
    if field.startswith("node_params."):
        node_params_key = field.split(".", 1)[1]
        if not node_params_key:
            return {"success": False, "message": "node_params 键名不能为空"}
    elif field not in _NODE_EDIT_FIELDS:
        return {
            "success": False,
            "message": f"不允许修改字段 {field}；允许：first_message / system_prompt_template / label / model_override / node_params.<键>",
        }

    wf_data = manager.get_workflow(workflow_id)
    if wf_data is None:
        return {"success": False, "message": f"工作流不存在: {workflow_id}"}
    definition = dict(wf_data["definition"])
    nodes = definition.get("nodes", [])
    target = next((n for n in nodes if n.get("id") == node_id), None)
    if target is None:
        return {
            "success": False,
            "message": f"工作流 {workflow_id} 中不存在节点 {node_id}",
        }

    if isinstance(new_value, str):
        new_value = new_value.strip()
    old_value = target.get(field)
    if node_params_key is not None:
        params = target.setdefault("node_params", {})
        old_value = params.get(node_params_key)
        params[node_params_key] = new_value
    else:
        target[field] = new_value

    validation = manager.validate_workflow(definition)
    if not validation.get("valid"):
        errors = "\n".join(validation.get("errors", ["校验失败"]))
        return {"success": False, "message": f"修改后工作流校验不通过：{errors}"}

    result = manager.update_workflow(workflow_id, definition)
    if result is None:
        return {"success": False, "message": "保存工作流失败"}
    return {
        "success": True,
        "message": f"已更新 {workflow_id} 节点 {node_id} 的 {field}（版本 {result['definition'].get('version')}）",
        "workflow_id": workflow_id,
        "node_id": node_id,
        "field": field,
        "old_value": str(old_value)[:500] if old_value is not None else "",
        "new_value": str(new_value)[:500],
        "reason": reason,
    }


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
