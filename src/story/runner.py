"""故事机器执行引擎与管理器。

StoryRunner：驱动一场对演（旁白 → 角色轮流四通道演出），
StoryManager：角色/会话的创建、持久化、生命周期与用户干预。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from src.config import SESSIONS_DIR
from src.characters.manager import get_character_manager
from src.characters.memory import append_memory, generate_character_log
from src.core.llm_client import create_llm
from src.story.models import (
    Character,
    StoryMessage,
    StorySession,
)
from src.story.personality import (
    EMOTION_KEYS,
    EMOTION_LABELS,
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
from src.story.prompts import (
    build_character_turn_messages,
    build_correction_messages,
    build_narrator_messages,
    format_transcript_tail,
)
from src.web.event_bus import event_bus

logger = logging.getLogger("story")


# ============================================================
# StoryRunner
# ============================================================

class StoryRunner:
    """驱动一场对演的主循环。"""

    def __init__(self, manager: "StoryManager"):
        self.manager = manager

    async def run(self, session: StorySession) -> None:
        session.status = "discussing"
        session.save()
        await event_bus.emit_chat({
            "type": "st_started",
            "story_id": session.session_id,
            "title": session.title,
            "character_ids": session.character_ids,
            "max_rounds": session.max_rounds,
        })

        try:
            while session.current_round < session.max_rounds:
                pause_event = self.manager.get_pause_event(session.session_id)
                await pause_event.wait()
                if session.status != "discussing":
                    break
                if await self._process_interventions(session):
                    break

                if session.narrator_enabled:
                    await self._narrator_turn(session)

                for cid in session.character_ids:
                    character = self.manager.get_character(cid)
                    if character is None:
                        continue
                    await pause_event.wait()
                    if session.status != "discussing":
                        break
                    if await self._process_interventions(session):
                        break
                    await self._character_turn(character, session)

                session.current_round += 1
                await event_bus.emit_chat({
                    "type": "st_round_end",
                    "story_id": session.session_id,
                    "round": session.current_round,
                })
                session.save()
        except asyncio.CancelledError:
            logger.info(f"故事 {session.session_id} 被取消")
            raise
        except Exception as e:
            logger.error(f"故事 {session.session_id} 异常: {e}", exc_info=True)

        # 为每个角色生成人物日志（跨会话记忆）
        await self._write_memory_logs(session)

        session.status = "ended"
        session.ended_at = datetime.now(timezone.utc).isoformat()
        session.save()
        await event_bus.emit_chat({
            "type": "st_ended",
            "story_id": session.session_id,
            "total_rounds": session.current_round,
            "transcript_count": len(session.transcript),
        })
        logger.info(
            f"故事 {session.session_id} 已结束：{session.current_round} 轮，"
            f"{len(session.transcript)} 条记录"
        )

    async def _write_memory_logs(self, session: StorySession) -> None:
        """会话结束后为每个角色生成并写入人物日志。"""
        if not session.transcript:
            return
        transcript_text = "\n".join(
            m.format_script() for m in session.transcript[-30:]
        )
        for cid in session.character_ids:
            character = self.manager.get_character(cid)
            if character is None:
                continue
            # 幂等：同一场戏不重复写入
            if any(m.get("session_id") == session.session_id for m in character.memory_logs):
                continue
            content = await generate_character_log(
                character,
                session.title,
                transcript_text,
                session_type="story",
            )
            if content:
                append_memory(
                    character,
                    content,
                    session.session_id,
                    "story",
                    session.title,
                )
                logger.info(
                    f"已为角色 {character.name} 写入人物日志（{session.session_id}）"
                )

    # ---------- 旁白 ----------

    async def _narrator_turn(self, session: StorySession) -> None:
        session.begin_active_turn("旁白", "narrator")
        await event_bus.emit_chat({
            "type": "st_turn_start",
            "story_id": session.session_id,
            "speaker_name": "旁白",
            "round": session.current_round,
            "entry_type": "narrator",
        })
        llm = create_llm(model_params={"temperature": 0.8}, streaming=True)
        messages = build_narrator_messages(session)
        content = ""
        try:
            async for chunk in llm.astream(messages):
                token = chunk.content if chunk.content else ""
                if token:
                    content += token
                    session.append_active_turn(token)
                    await event_bus.emit_chat({
                        "type": "st_token",
                        "story_id": session.session_id,
                        "speaker_name": "旁白",
                        "content": token,
                    })
        except Exception as e:
            logger.error(f"旁白生成异常: {e}", exc_info=True)
            content = "（夜色很静，两个人都没有先开口。）"

        msg = StoryMessage(
            speaker_name="旁白",
            entry_type="narrator",
            thinking=content,
            round_number=session.current_round,
        )
        session.transcript.append(msg)
        session.end_active_turn()
        session.save()
        await event_bus.emit_chat({
            "type": "st_turn_end",
            "story_id": session.session_id,
            "speaker_name": "旁白",
            "entry_type": "narrator",
            "content": content,
        })

    # ---------- 角色 ----------

    async def _character_turn(self, character: Character, session: StorySession) -> None:
        scene_text = session.scene_text()
        tail_text = format_transcript_tail(session.transcript)
        context_text = f"{scene_text}\n{tail_text}"

        # 事件触发 → 情绪偏移（认知评价后用于预估占比）
        event_hits, event_shift = trigger_events(character, context_text)
        projected = dict(character.emotion_state)
        for key, val in event_shift.items():
            projected[key] = clamp(projected.get(key, 0.0) + val)
        projected = appraise_emotion(character, projected)

        ratios = compute_ratios(character, projected)
        layer = behavior_layer(ratios["id"])
        depth = thinking_depth(ratios, stakes=0.5)

        other_names = [
            c.name for cid in session.character_ids
            if (c := self.manager.get_character(cid)) and c.character_id != character.character_id
        ]
        messages = build_character_turn_messages(
            character, session, event_hits, layer, depth, ratios, other_names
        )

        session.begin_active_turn(character.name, "character")
        await event_bus.emit_chat({
            "type": "st_turn_start",
            "story_id": session.session_id,
            "speaker_name": character.name,
            "character_id": character.character_id,
            "round": session.current_round,
            "layer": layer,
            "depth": depth,
            "entry_type": "character",
        })

        llm = create_llm(
            model_override=character.model_name,
            model_params={"temperature": character.temperature},
            streaming=True,
        )
        full_content = ""
        try:
            async for chunk in llm.astream(messages):
                token = chunk.content if chunk.content else ""
                if token:
                    full_content += token
                    session.append_active_turn(token)
                    await event_bus.emit_chat({
                        "type": "st_token",
                        "story_id": session.session_id,
                        "speaker_name": character.name,
                        "character_id": character.character_id,
                        "content": token,
                    })
        except Exception as e:
            logger.error(f"角色 {character.name} 演出异常: {e}", exc_info=True)
            full_content = f"【台词】「……（{character.name} 一时语塞）」"

        parsed = parse_turn(full_content)

        # 规则过滤：违规则修正一次，再兜底屏蔽
        violations = check_rules(character, parsed)
        if violations:
            corrected = await self._correct(character, violations, full_content)
            if corrected:
                parsed = corrected
            parsed = mask_violations(parsed, character)

        emotion = {k: clamp(parsed.get("emotion", {}).get(k, 0.0)) for k in EMOTION_KEYS}
        if not any(emotion.values()):
            emotion = projected

        update_state(character, emotion, event_hits)
        final_ratios = compute_ratios(character, emotion)
        character.current_ratio = final_ratios
        character.save()

        msg = StoryMessage(
            speaker_name=character.name,
            entry_type="character",
            thinking=parsed.get("thinking", ""),
            expression=parsed.get("expression", ""),
            action=parsed.get("action", ""),
            speech=parsed.get("speech", ""),
            emotion=emotion,
            round_number=session.current_round,
        )
        session.transcript.append(msg)
        session.end_active_turn()
        session.save()

        await event_bus.emit_chat({
            "type": "st_turn_end",
            "story_id": session.session_id,
            "speaker_name": character.name,
            "character_id": character.character_id,
            "round": session.current_round,
            "message": msg.to_dict(),
            "state": {
                "character_id": character.character_id,
                "current_ratio": final_ratios,
                "emotion_state": character.emotion_state,
                "layer": behavior_layer(final_ratios["id"]),
                "event_hits": [e.title for e in event_hits],
                "violations": violations,
            },
        })

    async def _correct(
        self, character: Character, violations: list[str], original: str
    ) -> dict | None:
        """违规修正：一次重写尝试。"""
        try:
            llm = create_llm(
                model_override=character.model_name,
                model_params={"temperature": 0.7},
                streaming=False,
            )
            response = await llm.ainvoke(
                build_correction_messages(character, violations, original)
            )
            content = response.content if response and response.content else ""
            parsed = parse_turn(content)
            if check_rules(character, parsed):
                return None
            return parsed
        except Exception as e:
            logger.warning(f"规则修正失败: {e}")
            return None

    # ---------- 用户干预 ----------

    async def _process_interventions(self, session: StorySession) -> bool:
        queue = self.manager.get_queue(session.session_id)
        should_stop = False
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            kind = item.get("type")
            if kind == "director":
                msg = StoryMessage(
                    speaker_name="导演",
                    entry_type="director",
                    thinking=item.get("content", ""),
                    round_number=session.current_round,
                )
                session.transcript.append(msg)
                await event_bus.emit_chat({
                    "type": "st_turn_end",
                    "story_id": session.session_id,
                    "speaker_name": "导演",
                    "entry_type": "director",
                    "content": msg.thinking,
                })
                session.save()
            elif kind == "pause":
                session.status = "paused"
                self.manager.get_pause_event(session.session_id).clear()
                await event_bus.emit_chat({
                    "type": "st_paused",
                    "story_id": session.session_id,
                    "round": session.current_round,
                })
                session.save()
                await self.manager.get_pause_event(session.session_id).wait()
                session.status = "discussing"
                await event_bus.emit_chat({
                    "type": "st_resumed",
                    "story_id": session.session_id,
                    "round": session.current_round,
                })
            elif kind == "end":
                should_stop = True
        return should_stop


# ============================================================
# StoryManager
# ============================================================

class StoryManager:
    """角色与会话的注册表 + 生命周期管理。"""

    def __init__(self):
        self._character_manager = get_character_manager()
        self.characters: dict[str, Character] = self._character_manager.characters
        self.sessions: dict[str, StorySession] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._pause_events: dict[str, asyncio.Event] = {}
        self._runner = StoryRunner(self)

    # ---------- 角色 ----------

    def save_character(self, data: dict) -> Character:
        return self._character_manager.save(data)

    def get_character(self, character_id: str) -> Character | None:
        return self._character_manager.get(character_id)

    def delete_character(self, character_id: str) -> bool:
        return self._character_manager.delete(character_id)

    def list_characters(self) -> list[dict]:
        return self._character_manager.list_all()

    def load_characters(self) -> None:
        self._character_manager.load_all()

    # ---------- 会话 ----------

    def create_session(
        self,
        title: str,
        scene: dict,
        character_ids: list[str],
        max_rounds: int = 8,
        narrator_enabled: bool = True,
    ) -> StorySession:
        valid_ids = [cid for cid in character_ids if cid in self.characters]
        session = StorySession(
            title=title,
            scene=scene,
            character_ids=valid_ids,
            narrator_enabled=narrator_enabled,
            max_rounds=max_rounds,
        )
        self.sessions[session.session_id] = session
        session.save()
        logger.info(
            f"故事 {session.session_id} 已创建：{title!r}, 角色={valid_ids}, "
            f"轮数={max_rounds}, 旁白={narrator_enabled}"
        )
        return session

    def get(self, session_id: str) -> StorySession | None:
        return self.sessions.get(session_id)

    def list_all(self) -> list[dict]:
        return [s.get_summary() for s in self.sessions.values()]

    def get_queue(self, session_id: str) -> asyncio.Queue:
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue()
        return self._queues[session_id]

    def get_pause_event(self, session_id: str) -> asyncio.Event:
        if session_id not in self._pause_events:
            self._pause_events[session_id] = asyncio.Event()
            self._pause_events[session_id].set()
        return self._pause_events[session_id]

    async def start(self, session_id: str) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到故事 {session_id}"}
        if session.status == "discussing":
            return {"success": False, "message": "该故事正在演出中"}
        if session.status == "ended":
            return {"success": False, "message": "该故事已结束"}
        if not session.character_ids:
            return {"success": False, "message": "故事没有可用角色"}

        self.get_pause_event(session_id).set()
        task = asyncio.create_task(
            self._run_session(session), name=f"story-{session_id}"
        )
        self._tasks[session_id] = task
        return {"success": True, "message": f"故事 {session_id} 已开演"}

    async def _run_session(self, session: StorySession) -> None:
        try:
            await self._runner.run(session)
        except asyncio.CancelledError:
            await self._finalize_interrupted_turn(session)
            # 即使被手动停止，也要为角色留下这场戏的日志
            await self._runner._write_memory_logs(session)
            session.status = "ended"
            session.ended_at = datetime.now(timezone.utc).isoformat()
            session.save()
        except Exception as e:
            logger.error(f"故事 {session.session_id} 运行异常: {e}", exc_info=True)
            await self._finalize_interrupted_turn(session)
            session.status = "ended"
            session.ended_at = datetime.now(timezone.utc).isoformat()
            session.save()
            await event_bus.emit_chat({
                "type": "st_ended",
                "story_id": session.session_id,
            })
        finally:
            self._tasks.pop(session.session_id, None)

    async def _finalize_interrupted_turn(self, session: StorySession) -> None:
        active = dict(session.active_turn) if session.active_turn else None
        session.end_active_turn()
        if not active or not active.get("content"):
            return
        content = str(active.get("content", ""))
        parsed = parse_turn(content)
        msg = StoryMessage(
            speaker_name=str(active.get("speaker_name", "")),
            entry_type=str(active.get("entry_type", "character")),
            thinking=parsed.get("thinking", ""),
            expression=parsed.get("expression", ""),
            action=parsed.get("action", ""),
            speech=parsed.get("speech", ""),
            round_number=session.current_round,
        )
        session.transcript.append(msg)
        await event_bus.emit_chat({
            "type": "st_turn_end",
            "story_id": session.session_id,
            "speaker_name": msg.speaker_name,
            "entry_type": msg.entry_type,
            "message": msg.to_dict(),
            "interrupted": True,
        })
        session.save()

    async def stop(self, session_id: str) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到故事 {session_id}"}
        if session.status not in ("discussing", "paused"):
            return {"success": False, "message": f"故事当前状态为 {session.status}"}
        if session.status == "paused":
            session.status = "discussing"
            self.get_pause_event(session_id).set()
        task = self._tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        session.status = "ended"
        session.ended_at = datetime.now(timezone.utc).isoformat()
        session.save()
        await event_bus.emit_chat({
            "type": "st_ended",
            "story_id": session_id,
            "total_rounds": session.current_round,
            "transcript_count": len(session.transcript),
        })
        return {"success": True, "message": f"故事 {session_id} 已结束"}

    async def pause(self, session_id: str) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到故事 {session_id}"}
        if session.status != "discussing":
            return {"success": False, "message": f"故事当前状态为 {session.status}，无法暂停"}
        await self.get_queue(session_id).put({"type": "pause"})
        return {"success": True, "message": "暂停指令已提交"}

    async def resume(self, session_id: str) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到故事 {session_id}"}
        if session.status != "paused":
            return {"success": False, "message": f"故事当前状态为 {session.status}，无法恢复"}
        session.status = "discussing"
        self.get_pause_event(session_id).set()
        await event_bus.emit_chat({
            "type": "st_resumed",
            "story_id": session_id,
            "round": session.current_round,
        })
        return {"success": True, "message": "故事已恢复"}

    async def inject(self, session_id: str, content: str) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到故事 {session_id}"}
        if session.status not in ("discussing", "paused"):
            return {"success": False, "message": f"故事状态为 {session.status}，无法注入"}
        await self.get_queue(session_id).put({"type": "director", "content": content})
        return {"success": True, "message": "导演指令已注入"}

    async def set_emotion(
        self,
        session_id: str,
        character_id: str,
        emotion: dict | None = None,
        ratios: dict | None = None,
        clear: bool = False,
    ) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到故事 {session_id}"}
        character = self.characters.get(character_id)
        if not character:
            return {"success": False, "message": f"未找到角色 {character_id}"}
        if clear:
            character.pinned_emotion = None
            character.pinned_ratios = None
        else:
            if emotion is not None:
                character.pinned_emotion = {
                    k: clamp(float(emotion.get(k, 0.0))) for k in EMOTION_KEYS
                }
            if ratios is not None:
                from src.story.personality import normalize_ratios
                character.pinned_ratios = normalize_ratios(ratios)
        character.save()
        await event_bus.emit_chat({
            "type": "st_state",
            "story_id": session_id,
            "character_id": character_id,
            "state": {
                "pinned_emotion": character.pinned_emotion,
                "pinned_ratios": character.pinned_ratios,
            },
        })
        return {"success": True, "message": "角色状态已更新"}

    def export_markdown(self, session_id: str) -> str | None:
        session = self.sessions.get(session_id)
        if not session:
            return None
        lines = [f"# {session.title}", ""]
        scene = session.scene_text()
        if scene:
            lines += ["## 场景", "", scene, ""]
        lines.append("## 剧本")
        lines.append("")
        for msg in session.transcript:
            if msg.entry_type == "narrator":
                lines.append(msg.thinking or msg.speech)
                lines.append("")
            elif msg.entry_type == "director":
                lines.append(f"**[导演]** {msg.thinking or msg.speech}")
                lines.append("")
            else:
                if msg.thinking:
                    lines.append(f"> 内心：{msg.thinking}")
                parts = []
                if msg.expression:
                    parts.append(f"（{msg.expression}）")
                if msg.action:
                    parts.append(msg.action)
                if msg.speech:
                    parts.append(f"「{msg.speech}」")
                lines.append(f"**{msg.speaker_name}**：{' '.join(parts)}")
                lines.append("")
        return "\n".join(lines)

    async def delete(self, session_id: str) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            return {"success": False, "message": f"未找到故事 {session_id}"}
        if session.status == "discussing":
            return {"success": False, "message": "不能删除演出中的故事，请先结束"}
        task = self._tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.pop(session_id, None)
        self.sessions.pop(session_id, None)
        self._queues.pop(session_id, None)
        self._pause_events.pop(session_id, None)
        file_path = SESSIONS_DIR / f"{session_id}.json"
        if file_path.exists():
            file_path.unlink()
        return {"success": True, "message": f"故事 {session_id} 已删除"}

    def load_sessions(self) -> None:
        if not SESSIONS_DIR.exists():
            return
        for file_path in SESSIONS_DIR.glob("st-*.json"):
            try:
                session = StorySession.load(file_path.stem)
                if session:
                    if session.status == "discussing":
                        session.status = "ended"
                        session.ended_at = datetime.now(timezone.utc).isoformat()
                        session.save()
                    self.sessions[session.session_id] = session
            except Exception as e:
                logger.error(f"加载故事 {file_path.stem} 失败: {e}")

    async def shutdown(self) -> None:
        for session_id, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        for session in self.sessions.values():
            if session.status == "discussing":
                session.status = "ended"
                session.ended_at = datetime.now(timezone.utc).isoformat()
            session.save()
        self._tasks.clear()
        logger.info("StoryManager 已关闭")
