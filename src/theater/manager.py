"""剧场管理器：世界 CRUD、会话创建、AI 预读取、开演调度。"""

from __future__ import annotations

import logging
import asyncio
import json
import re
from pathlib import Path

from src.characters.manager import get_character_manager
from src.characters.models import Character
from src.config import DATA_DIR
from src.theater.battle import resolve
from src.theater.models import TheaterSession, World


EMOTION_CN = {
    "anger": "愤怒", "fear": "恐惧", "sadness": "悲伤", "joy": "喜悦",
    "calm": "冷静", "determination": "坚定", "disgust": "厌恶", "surprise": "惊讶",
    "trust": "信任", "anticipation": "期待",
}


def emotion_summary(emotion_state: dict) -> dict:
    """取强度最高的情绪，返回中文综合情绪名与强度。

    情绪不是"一段一段"的，而是综合成当前主导情绪（如"愤怒"），供小说输出使用。
    """
    if not emotion_state:
        return {"name": "平静", "value": 0.0}
    best_key = ""
    best_val = 0.0
    for k, v in emotion_state.items():
        try:
            val = float(v)
        except (TypeError, ValueError):
            continue
        if val > best_val:
            best_val = val
            best_key = str(k).lower()
    return {
        "name": EMOTION_CN.get(best_key, best_key),
        "value": round(best_val, 2),
    }


def _scene_anchor(location: str) -> str:
    """从地点描述提取场景锚点词（如"打烊的咖啡馆"→"咖啡馆"）。"""
    loc = re.sub(r"[，。；、/：\s（）()]", "", location or "")
    loc = loc.replace("的", "")
    if not loc:
        return ""
    return loc[-3:] if len(loc) >= 3 else loc

logger = logging.getLogger("theater")

WORLDS_DIR = Path(DATA_DIR) / "worlds"


class TheaterManager:
    """管理世界与剧场会话。"""

    def __init__(self) -> None:
        self.worlds: dict[str, World] = {}
        self.sessions: dict[str, TheaterSession] = {}
        WORLDS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_worlds()

    # ---------- 世界 ----------
    def _load_worlds(self) -> None:
        for f in WORLDS_DIR.glob("wx-*.json"):
            w = World.load(f.stem)
            if w:
                self.worlds[w.world_id] = w

    def list_worlds(self) -> list[dict]:
        return [w.to_dict() for w in self.worlds.values()]

    def create_world(self, name: str, worldview: str = "", skill_ids: list[str] | None = None) -> World:
        w = World(name=name, worldview=worldview, skill_ids=list(skill_ids or []))
        w.save()
        self.worlds[w.world_id] = w
        logger.info(f"世界已创建: {w.world_id} ({name})")
        return w

    def get_world(self, world_id: str) -> World | None:
        return self.worlds.get(world_id)

    def update_world(self, world_id: str, **updates) -> World | None:
        w = self.worlds.get(world_id)
        if not w:
            return None
        for key, val in updates.items():
            if hasattr(w, key) and val is not None:
                setattr(w, key, val)
        w.save()
        return w

    def delete_world(self, world_id: str) -> bool:
        w = self.worlds.pop(world_id, None)
        if not w:
            return False
        path = WORLDS_DIR / f"{world_id}.json"
        if path.exists():
            path.unlink()
        return True

    # ---------- 剧场会话 ----------
    def create_session(
        self,
        world_id: str,
        mode: str = "perform",
        title: str = "未命名演出",
        character_ids: list[str] | None = None,
        scene: dict | None = None,
        battle_ratio: int = 70,
        model_override: str | None = None,
    ) -> TheaterSession:
        session = TheaterSession(
            world_id=world_id,
            mode=mode,
            title=title,
            character_ids=list(character_ids or []),
            scene=dict(scene or {}),
            battle_ratio=battle_ratio,
            model_override=model_override,
        )
        session.save()
        self.sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> TheaterSession | None:
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        return [s.to_dict() for s in self.sessions.values()]

    def set_battle_ratio(self, session_id: str, ratio: int) -> bool:
        s = self.sessions.get(session_id)
        if not s:
            return False
        s.battle_ratio = max(0, min(100, int(ratio)))
        s.save()
        return True

    # ---------- AI 预读取 ----------
    async def pre_read(self, session_id: str) -> dict:
        """读取世界观/角色/装备/Skills，调用 LLM 生成共识摘要。"""
        from src.core.llm_client import create_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": "会话不存在"}
        world = self.worlds.get(session.world_id)
        if not world:
            return {"success": False, "message": "世界不存在"}

        steps: list[dict] = []
        characters: list[Character] = []

        def mark(key: str, label: str, ok: bool, note: str = "") -> None:
            steps.append({"key": key, "label": label, "status": "done" if ok else "failed", "note": note})

        # 1. 世界观
        mark("world", "世界观", bool(world.worldview.strip()), world.name)
        # 2. 角色卡
        cm = get_character_manager()
        for cid in session.character_ids:
            c = cm.get(cid)
            if c:
                characters.append(c)
        mark("char", "角色卡 ×%d" % len(characters), len(characters) > 0,
             "、".join(c.name for c in characters))
        # 3. 装备
        eq_total = sum(len(c.equipment) for c in characters)
        mark("eqp", "装备 / 道具", eq_total > 0, f"{eq_total} 件")
        # 4. Skills（世界 + 角色）
        skill_ids = list(world.skill_ids)
        for c in characters:
            skill_ids.extend(c.skill_ids)
        mark("skill", "Skills 写作风格", len(skill_ids) > 0, f"{len(skill_ids)} 个")
        # 5. 场景
        mark("scene", "场景设定", bool(session.scene), session.title)

        # 组装预读取材料
        char_lines = []
        for c in characters:
            stats = "、".join(f"{k}{v}" for k, v in c.stats.items())
            eq = "、".join(f"{e.get('name','')}" for e in c.equipment) or "无"
            char_lines.append(
                f"- {c.name}（类型:{'/'.join(c.types) or '通用'} 五维:{stats} 装备:{eq} 情绪:{c.emotion_state or '平静'}）"
            )
        material = (
            f"世界：{world.name}\n世界观：{world.worldview}\n"
            f"已发生剧情：{'；'.join(world.history) or '无'}\n\n"
            f"角色：\n" + "\n".join(char_lines) +
            f"\n\n场景：{session.scene}"
        )

        try:
            llm = create_llm(model_params={"temperature": 0.3}, streaming=False)
            system_prompt = (
                "你是剧场导演，负责开演前整理「共识摘要」。"
                "用中文输出 3-5 句，概括本场开局必须遵守的既定事实，"
                "包括世界观约束、角色状态、装备、场景。"
            )
            resp = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=material),
            ])
            consensus = str(resp.content).strip()
            mark("consensus", "生成共识摘要", bool(consensus))
        except Exception as e:
            logger.error(f"预读取共识摘要失败: {e}", exc_info=True)
            consensus = "（共识摘要生成失败，按世界观与角色卡直接开演）"
            mark("consensus", "生成共识摘要", False, str(e))

        session.pre_read_done = True
        session.pre_read_steps = steps
        session.consensus = consensus
        session.save()
        return {
            "success": True,
            "steps": steps,
            "consensus": consensus,
            "session": session.to_dict(),
        }

    # ---------- 战斗判定（供路由调用） ----------
    async def battle_action(self, session_id: str, attacker_id: str, defender_id: str,
                            action: str, attack_stat: str = "力量", defense_stat: str = "敏捷") -> dict:
        session = self.sessions.get(session_id)
        cm = get_character_manager()
        atk = cm.get(attacker_id)
        dfn = cm.get(defender_id) if defender_id else None
        if not atk:
            return {"success": False, "message": f"角色不存在: {attacker_id}"}
        ratio = session.battle_ratio if session else 70
        result = resolve(
            attacker_stats=atk.stats,
            defender_stats=dfn.stats if dfn else None,
            abilities=atk.abilities,
            equipment=atk.equipment,
            emotion_state=atk.emotion_state,
            attack_stat=attack_stat,
            defense_stat=defense_stat,
            ratio=ratio,
        )
        result["action"] = action
        result["attacker"] = atk.name
        result["defender"] = dfn.name if dfn else "环境"
        return {"success": True, "result": result}

    # ---------- 演出（AI 生成，接世界观/角色/情绪/Skills 风格） ----------
    def _build_world_context(self, world: World | None) -> str:
        if not world:
            return "（未设置世界观）"
        parts = [f"世界观：{world.worldview}"]
        if world.history:
            parts.append("已发生剧情：" + "；".join(world.history[-5:]))
        if world.skill_ids:
            parts.append("世界写作风格：" + "、".join(world.skill_ids))
        return "\n".join(parts)

    @staticmethod
    def _parse_turn(text: str) -> dict:
        """从 LLM 输出解析四通道（思考/表情/动作/台词），兼容 JSON 与标签格式。"""
        text = text.strip()
        # 去掉 ```json ... ``` 代码块包裹
        if text.startswith("```"):
            m = re.match(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
            if m:
                text = m.group(1).strip()
        # 尝试 JSON
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {
                    "thinking": str(data.get("thinking", "")).strip(),
                    "expression": str(data.get("expression", "")).strip(),
                    "action": str(data.get("action", "")).strip(),
                    "speech": str(data.get("speech", "")).strip(),
                }
        except (json.JSONDecodeError, TypeError):
            pass
        # 标签格式：【情绪】【内心】【表情】【动作】【台词】
        result = {"thinking": "", "expression": "", "action": "", "speech": ""}
        mapping = {
            "内心": "thinking", "思考": "thinking", "情绪": "thinking",
            "表情": "expression", "动作": "action", "台词": "speech",
        }
        for key, field in mapping.items():
            m = re.search(rf"【{key}】\s*(.+?)(?=【|$)", text, re.S)
            if m:
                result[field] = m.group(1).strip()
        if not result["speech"]:
            # 兜底：整段当台词
            result["speech"] = text
        return result

    async def perform_round(self, session_id: str, director: str = "") -> dict:
        """执行一轮演出：AI 直接生成一段小说正文（叙述体）。

        输出是小说正文：场景描写、角色动作、对话自然融合，
        不使用舞台指示/括号标注，符合网络小说文风。
        战斗场景时用小说式文字描写打斗（参考网文）。
        """
        from src.core.llm_client import create_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": "会话不存在"}
        world = self.worlds.get(session.world_id)
        cm = get_character_manager()
        chars = [cm.get(cid) for cid in session.character_ids if cm.get(cid)]
        if not chars:
            return {"success": False, "message": "没有可用角色"}

        is_battle = str(session.scene.get("scene_type", "")) == "battle"
        world_ctx = self._build_world_context(world)
        record = getattr(session, "record", [])

        # ---------- 生成一段小说正文 ----------
        char_summaries = []
        for c in chars:
            emo = emotion_summary(c.emotion_state or {})
            char_summaries.append(
                f"- {c.name}：类型{'/'.join(c.types) or '通用'}，当前情绪{emo['name']}"
                f"（强度{emo['value']}），压力{c.pressure}，"
                f"五维{'、'.join(f'{k}{v}' for k, v in c.stats.items())}，"
                f"装备{'、'.join(e.get('name','') for e in c.equipment) or '无'}，"
                f"写作风格{'、'.join(c.skill_ids) or '无'}"
            )
        char_block = "\n".join(char_summaries)

        scene_loc = str(session.scene.get("location", ""))
        scene_time = str(session.scene.get("time", ""))
        scene_mood = str(session.scene.get("mood", ""))
        scene_anchor = _scene_anchor(scene_loc)
        scene_force = (
            f"【强制场景（绝不可违反）】地点：{scene_loc or '未指定'}。"
            f"时间：{scene_time or '未指定'}。气氛：{scene_mood or '未指定'}。"
            "你写的每一句都必须发生在这个地点和时间里，禁止更换地点、时间，禁止出现与设定无关的环境。"
        )
        if is_battle:
            novel_sys = (
                "你是一位网络小说作家，正在写一场战斗。"
                f"{scene_force}"
                "请用小说正文的形式描写这场打斗：有招式动作、攻防转换、环境互动、力量与速度的对比，"
                "像小说章节一样有画面感和张力。角色对话用引号自然融入叙述。"
                "禁止舞台指示、禁止括号标注，直接写小说正文。篇幅 150-300 字。"
            )
        else:
            novel_sys = (
                "你是一位网络小说作家。"
                f"{scene_force}"
                "请用小说正文的形式推进剧情：场景描写、角色动作、心理、对话自然融合成一段连贯的小说段落，"
                "文风有画面感和代入感。角色对话用引号自然融入叙述。"
                "禁止舞台指示、禁止括号标注，直接写小说正文。篇幅 150-300 字。"
            )
        # 场景写法示例（few-shot）：让模型模仿场景与文风
        scene_example = (
            f"\n\n【场景写法示例（模仿它的地点与文风，不要照抄内容）】\n"
            f"{scene_loc or '咖啡馆'}里光线昏暗，桌椅的阴影在墙上一动不动。"
            f"{scene_time or '深夜'}，只有角落那盏灯还亮着，"
            f"空气里弥漫着{scene_mood or '压抑'}的气息。"
            "沈默坐在窗边，指节无意识地摩挲着杯沿。"
        )
        novel_user = (
            f"【本段场景（硬约束，禁止更改）】\n地点：{scene_loc or '未指定'}；"
            f"时间：{scene_time or '未指定'}；气氛：{scene_mood or '未指定'}。\n"
            "本段所有内容必须发生在这个场景中，禁止写其他地点、禁止跳过场景直接换地方。\n\n"
            f"正文第一句话必须直接出现「{scene_anchor or scene_loc}」这个地点词。\n\n"
            f"{scene_example}\n\n"
            f"{world_ctx}\n\n出场角色：\n{char_block}\n\n"
            f"已写剧情：\n" + ("\n".join(str(x) for x in record[-6:]) or "（这是故事开头）")
            + (f"\n\n导演指令：{director}" if director else "")
            + "\n\n请严格按照系统提示中的【强制场景】，接着写这一段小说正文。"
        )
        # 场景锚点校验：正文必须出现场景地点词，否则重写一次
        novel_text = ""
        try:
            llm = create_llm(
                # 智谱 GLM 系列场景遵循与文笔更稳（实测 DeepSeek 会擅自换场景）
                model_override=session.model_override or "zhipu:glm-4.6",
                model_params={"temperature": 0.65, "thinking_enabled": False},
                streaming=False,
            )
            for attempt in range(2):
                resp = await llm.ainvoke([
                    SystemMessage(content=novel_sys),
                    HumanMessage(content=novel_user),
                ])
                text = str(resp.content).strip()
                if not scene_anchor or scene_anchor in text or attempt == 1:
                    novel_text = text
                    break
                # 未包含场景锚点：强制纠正重写
                novel_user = (
                    f"你上一版场景写错了。唯一允许的地点就是【{scene_loc}】。"
                    f"请重写，正文第一句必须是「{scene_anchor}」。"
                    f"时间：{scene_time}；气氛：{scene_mood}。\n\n"
                    + novel_user
                )
            if not novel_text:
                novel_text = text if "text" in dir() else "夜色渐深，咖啡馆里只剩下两个人的呼吸声。"
        except Exception as e:
            logger.error(f"小说生成失败: {e}")
            novel_text = "夜色渐深，咖啡馆里只剩下两个人的呼吸声。"

        record.append(novel_text)
        # 简单情绪演算：压力累积
        for c in chars:
            c.pressure = min(100, (c.pressure or 0) + 2)

        session.record = record
        session.save()
        return {
            "success": True,
            "round": len(record),
            "narrator": novel_text,  # 一段小说正文
            "turns": [],  # 小说模式：不再分角色四通道
            "is_battle": is_battle,
            "battle_ratio": session.battle_ratio,
            "session": session.to_dict(),
        }

    async def _gen_char_turn(
        self, c, world_ctx, session, is_battle, record, other_names,
    ) -> dict:
        """生成单个角色的四通道发言（可并行）。"""
        from src.core.llm_client import create_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        emo = emotion_summary(c.emotion_state or {})
        emotion_note = f"当前情绪：{emo['name']}（强度 {emo['value']}），压力 {c.pressure}"
        stats_note = "；".join(f"{k}{v}" for k, v in c.stats.items())
        eq_note = "、".join(
            f"{e.get('name','')}({e.get('effect','')})" for e in c.equipment
        ) or "无"
        skills_note = "、".join(c.skill_ids) or "无"
        char_sys = (
            f"你是小说角色「{c.name}」。"
            f"类型：{'/'.join(c.types) or '通用'}。"
            f"性格：三我占比 {c.base_ratio}，特质：{', '.join(t.name for t in c.traits) or '无'}。"
            f"写作风格（SKILL）：{skills_note}——按风格控制你的讲话时机与方式。"
            f"{emotion_note}，身体素质：{stats_note}，装备：{eq_note}。"
            "你的话必须符合人设与世界观，情绪影响措辞与动作。"
        )
        char_user = (
            f"{world_ctx}\n\n场景：{session.scene}\n\n最近的剧情：\n"
            + ("\n".join(str(x) for x in record[-8:]) or "（开场）")
            + f"\n\n轮到 {c.name} 发言。场上还有：{'、'.join(n for n in other_names if n != c.name)}。"
            + ("\n\n这是战斗场景，你的动作可以是攻击/防御/闪避，但要具体、像小说。"
               if is_battle else "")
            + "\n请严格按 JSON 输出：{\"thinking\":\"内心想法\",\"expression\":\"表情\",\"action\":\"动作\",\"speech\":\"台词\"}"
        )
        llm = create_llm(model_params={"temperature": 0.8}, streaming=False)
        resp = await llm.ainvoke([
            SystemMessage(content=char_sys),
            HumanMessage(content=char_user),
        ])
        turn = self._parse_turn(str(resp.content))
        turn["character_id"] = c.character_id
        turn["name"] = c.name
        turn["emotion"] = emo  # 综合情绪（中文名 + 强度）
        return turn


_manager: TheaterManager | None = None


def get_theater_manager() -> TheaterManager:
    global _manager
    if _manager is None:
        _manager = TheaterManager()
    return _manager
