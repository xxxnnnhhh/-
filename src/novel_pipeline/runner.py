"""小说管线运行器：把子工作流任务一个接一个自动跑完。

核心机制：
- 所有子工作流任务共享同一个 workspace_override（小说项目工作区），
  前一个工作流写的 meta/、outline/、story/ 等文件直接被下一个读取；
- 每个步骤是 WorkflowManager 的一个独立任务，跑完上一个自动启动下一个；
- 章节循环：逐章依次执行「生产 → 后验 → 润色」，参数自动带入章节号；
- 全部跑完后自动合成完整文本并 E 盘存档。
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .assemble import assemble_full_text
from .models import (
    NovelProject,
    PipelineStep,
    TERMINAL_TASK_STATUSES,
    ensure_dirs,
    save_project,
    workspace_path,
)

if TYPE_CHECKING:
    from src.workflow.manager import WorkflowManager

logger = logging.getLogger(__name__)


class NovelPipelineRunner:
    def __init__(self, manager: "WorkflowManager"):
        self._manager = manager
        self._running: dict[str, asyncio.Task] = {}
        ensure_dirs()

    # ------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------

    def is_running(self, project_id: str) -> bool:
        task = self._running.get(project_id)
        return task is not None and not task.done()

    def start(self, project: NovelProject, *, reset: bool = False) -> dict:
        if self.is_running(project.project_id):
            return {
                "success": False,
                "message": "该小说已在连跑中，请先停止再重新开始",
            }
        if reset:
            project.steps = project.build_steps()
        elif not project.steps:
            project.steps = project.build_steps()
        # 失败/停止过的步骤允许从断点继续，已完成的保留
        for step in project.steps:
            if step.status in {"failed", "stopped"}:
                step.status = "pending"
                step.task_id = ""
                step.error = ""
        project.status = "running"
        project.error = ""
        project.current_step = ""
        save_project(project)
        self._emit(project)

        coro = asyncio.create_task(self._run_coro(project))
        self._running[project.project_id] = coro
        return {"success": True, "message": "小说连跑已启动", "project_id": project.project_id}

    def start_single(self, project: NovelProject, step_key: str) -> dict:
        """只运行流水线中的某一个步骤（如：世界观构建、卷纲近纲规划），
        在作品工作台里原地执行，不用跳到流水线页。"""
        if self.is_running(project.project_id):
            return {
                "success": False,
                "message": "当前已有任务在运行，请先停止",
            }
        step = next((s for s in project.steps if s.key == step_key), None)
        if step is None:
            return {"success": False, "message": f"未知步骤: {step_key}"}
        step.status = "pending"
        step.task_id = ""
        step.error = ""
        project.status = "running"
        project.error = ""
        project.current_step = step_key
        save_project(project)
        self._emit(project)
        coro = asyncio.create_task(self._run_single_coro(project, step))
        self._running[project.project_id] = coro
        return {
            "success": True,
            "message": f"已开始：{step.label}",
            "project_id": project.project_id,
            "step_key": step_key,
        }

    async def _run_single_coro(self, project: NovelProject, step: PipelineStep) -> None:
        """单步运行：跑完把项目状态恢复为 idle（不是整书完成）。"""
        try:
            try:
                task_id = await self._run_one(project, step)
                step.status = "completed"
                step.error = ""
                step.completed_at = _now_iso()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                step.status = "failed"
                step.error = str(exc)[:2000]
                step.completed_at = _now_iso()
                project.status = "failed"
                project.error = f"{step.label} 失败：{step.error}"
                save_project(project)
                self._emit(project)
                return
            project.status = "idle"
            project.error = ""
            project.current_step = ""
            save_project(project)
            self._emit(project)
        except asyncio.CancelledError:
            project.status = "stopped"
            save_project(project)
            self._emit(project)
            raise
        finally:
            self._running.pop(project.project_id, None)

    async def stop(self, project_id: str) -> dict:
        task = self._running.get(project_id)
        project = self._load(project_id)
        if task is None or task.done():
            if project is not None and project.status == "running":
                project.status = "stopped"
                save_project(project)
                self._emit(project)
            return {"success": True, "message": "小说未在连跑"}
        # 先尽力停掉当前子工作流任务
        if project is not None and project.current_step:
            step = next((s for s in project.steps if s.key == project.current_step), None)
            if step and step.task_id:
                try:
                    await self._manager.stop_task(step.workflow_id, step.task_id)
                except Exception:
                    logger.exception("停止子任务失败: %s", step.task_id)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        self._running.pop(project_id, None)
        if project is not None:
            project.status = "stopped"
            save_project(project)
            self._emit(project)
        return {"success": True, "message": "小说连跑已停止"}

    # ------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------

    def _load(self, project_id: str) -> NovelProject | None:
        from .models import load_project
        return load_project(project_id)

    async def _run_coro(self, project: NovelProject) -> None:
        try:
            for step in project.steps:
                if project.status != "running":
                    break
                if step.status == "completed":
                    continue
                project.current_step = step.key
                step.status = "running"
                step.started_at = _now_iso()
                save_project(project)
                self._emit(project)
                try:
                    task_id = await self._run_one(project, step)
                    step.status = "completed"
                    step.error = ""
                    step.completed_at = _now_iso()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    step.status = "failed"
                    step.error = str(exc)[:2000]
                    step.completed_at = _now_iso()
                    project.status = "failed"
                    project.error = f"{step.label} 失败：{step.error}"
                    save_project(project)
                    self._emit(project)
                    return
                save_project(project)
                self._emit(project)

            if project.status != "running":
                return

            # 全部子工作流跑完 → 合成完整文本
            project.current_step = "assemble"
            save_project(project)
            self._emit(project)
            try:
                final_path, archive_path = assemble_full_text(project)
                project.final_text_path = final_path
                project.archive_path = archive_path
                project.status = "completed"
                project.error = ""
            except Exception as exc:
                logger.exception("合成完整文本失败")
                project.status = "failed"
                project.error = f"全文合成失败：{exc}"
            project.current_step = ""
            save_project(project)
            self._emit(project)
        except asyncio.CancelledError:
            project.status = "stopped"
            save_project(project)
            self._emit(project)
            raise
        finally:
            self._running.pop(project.project_id, None)

    async def _run_one(self, project: NovelProject, step: PipelineStep) -> str:
        """创建并运行一个子工作流任务，等待其自然结束。"""
        params = project.step_params(step)
        result = self._manager.create_task(
            step.workflow_id,
            parameter_values=params,
            workspace_override=project.workspace,
        )
        if result is None:
            raise RuntimeError(
                f"工作流 {step.workflow_id} 不存在或不可用，请确认笔枢插件已启用"
            )
        task_id = result["task_id"]
        # 立刻把 task_id 落盘：运行中也能「查看任务」/「停止当前子任务」
        step.task_id = task_id
        save_project(project)
        self._emit(project)
        started = await self._manager.run_task(step.workflow_id, task_id)
        if not started.get("success"):
            raise RuntimeError(started.get("message", "任务启动失败"))

        while True:
            data = self._manager.get_task_with_definition(step.workflow_id, task_id)
            if data is None:
                # 引擎原子写盘时偶发瞬时不可读，重试几次再判定丢失
                for _ in range(5):
                    await asyncio.sleep(3)
                    data = self._manager.get_task_with_definition(step.workflow_id, task_id)
                    if data is not None:
                        break
                if data is None:
                    raise RuntimeError("任务状态文件丢失")
            task = data.get("task") or {}
            status = task.get("status", "")
            if status == "completed":
                return task_id
            if status in {"failed", "stopped", "cancelled"}:
                error = task.get("error") or task.get("status")
                # 失败时尽量给出具体原因（取第一个失败节点）
                node_error = self._first_node_error(task)
                raise RuntimeError(node_error or error or f"任务状态：{status}")
            # 还在跑：等待下一次状态更新后重新读取
            await self._manager.wait_for_task_update(
                step.workflow_id, task_id, timeout_seconds=15,
            )

    @staticmethod
    def _first_node_error(task: dict) -> str:
        node_states = task.get("node_states") or {}
        for state in node_states.values():
            if isinstance(state, dict) and state.get("status") == "failed" and state.get("error"):
                label = state.get("node_id") or ""
                return f"节点 {label}：{str(state['error'])[:1500]}"
        return ""

    def _emit(self, project: NovelProject) -> None:
        try:
            from src.web.event_bus import event_bus
            asyncio.create_task(event_bus.emit_event({
                "type": "novel_pipeline_update",
                "project_id": project.project_id,
                "status": project.status,
                "current_step": project.current_step,
                "steps": [s.to_dict() for s in project.steps],
                "final_text_path": project.final_text_path,
                "archive_path": project.archive_path,
                "error": project.error,
            }))
        except Exception:
            logger.debug("novel_pipeline_update 事件推送失败", exc_info=True)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
