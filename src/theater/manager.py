"""剧场管理器：世界 CRUD、会话创建、AI 预读取、开演调度。"""

from __future__ import annotations

import logging
from pathlib import Path

from src.characters.manager import get_character_manager
from src.characters.models import Character
from src.config import DATA_DIR
from src.theater.battle import resolve
from src.theater.models import TheaterSession, World

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
    ) -> TheaterSession:
        session = TheaterSession(
            world_id=world_id,
            mode=mode,
            title=title,
            character_ids=list(character_ids or []),
            scene=dict(scene or {}),
            battle_ratio=battle_ratio,
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


_manager: TheaterManager | None = None


def get_theater_manager() -> TheaterManager:
    global _manager
    if _manager is None:
        _manager = TheaterManager()
    return _manager
