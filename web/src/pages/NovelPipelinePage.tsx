/**
 * 小说管线：把笔枢写作工作流串成一条流水线。
 * 建书 → 一键连跑（世界观→角色→故事规划→卷纲近纲→逐章生产/后验/润色）→ 完整文本。
 * 每个步骤都可以点开对应工作流查看/修改。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpenText, Plus, Play, RotateCcw, Square, RefreshCw, Download,
  FolderOpen, FileText, ArrowRight, Loader2, Trash2, CheckCircle2,
  XCircle, Clock, PauseCircle, Circle, ExternalLink, Sparkles,
} from "lucide-react";
import { useWebSocket } from "../hooks/useWebSocket";

interface PipelineStep {
  key: string;
  label: string;
  workflow_id: string;
  workflow_name: string;
  status: "pending" | "running" | "completed" | "failed";
  task_id: string;
  error: string;
  chapter_number: string;
  started_at: string;
  completed_at: string;
}

interface NovelProject {
  project_id: string;
  name: string;
  premise: string;
  genre: string;
  language: string;
  chapters: number[];
  target_word_count: string;
  estimated_length: string;
  words_per_chapter: string;
  human_intent: string;
  world_intent: string;
  writer_type: string;
  created_at: string;
  updated_at: string;
  status: "idle" | "running" | "completed" | "failed" | "stopped";
  current_step: string;
  error: string;
  workspace: string;
  final_text_path: string;
  archive_path: string;
  steps: PipelineStep[];
}

const EMPTY_FORM = {
  name: "",
  premise: "",
  genre: "",
  language: "中文",
  chapters: "1,2,3",
  target_word_count: "3000-4000",
  estimated_length: "中",
  words_per_chapter: "2000-2500",
  human_intent: "",
  world_intent: "",
  writer_type: "single",
};

const STATUS_META: Record<string, { label: string; icon: typeof Circle; cls: string }> = {
  pending: { label: "等待", icon: Circle, cls: "text-slate-500" },
  running: { label: "运行中", icon: Loader2, cls: "text-amber-400 animate-spin" },
  completed: { label: "完成", icon: CheckCircle2, cls: "text-emerald-400" },
  failed: { label: "失败", icon: XCircle, cls: "text-red-400" },
};

function workflowName(id: string): string {
  const map: Record<string, string> = {
    "bishu-novel-build": "世界观构建管线",
    "bishu-novel-character": "角色创建管线",
    "bishu-novel-story-plan": "故事宏观规划",
    "bishu-novel-outline": "卷纲+近纲规划管线",
    "bishu-novel-mvp": "章节生产管线",
    "bishu-novel-post-hoc": "章节后验管线",
    "bishu-novel-polish": "章节润色管线",
  };
  return map[id] || id;
}

export default function NovelPipelinePage() {
  const [projects, setProjects] = useState<NovelProject[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [textModal, setTextModal] = useState<{ name: string; content: string; path: string; archive: string } | null>(null);
  const [filesOpen, setFilesOpen] = useState(false);
  const [files, setFiles] = useState<{ path: string; size: number }[]>([]);
  const [connected, setConnected] = useState(false);

  const selected = useMemo(
    () => projects.find((p) => p.project_id === selectedId) || null,
    [projects, selectedId],
  );

  const fetchProjects = useCallback(async () => {
    try {
      const res = await fetch("/api/novel/pipelines");
      if (!res.ok) return;
      const data = await res.json();
      const list: NovelProject[] = data.projects || [];
      setProjects(list);
      setSelectedId((cur) => cur && list.some((p) => p.project_id === cur) ? cur : (list[0]?.project_id ?? null));
    } catch {
      setMessage("小说项目列表加载失败");
    }
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  // 实时刷新：连跑过程中后端每步都会推送 novel_pipeline_update
  useWebSocket({
    url: "/ws/events",
    autoConnect: true,
    onMessage: useCallback((raw: unknown) => {
      const evt = raw as { type?: string; project_id?: string; status?: string };
      if (evt?.type !== "novel_pipeline_update") return;
      setConnected(true);
      fetchProjects();
      if (evt.status === "completed" || evt.status === "failed" || evt.status === "stopped") {
        setTimeout(() => setConnected(false), 3000);
      }
    }, [fetchProjects]),
  });

  const openWorkflow = (workflowId: string, taskId?: string) => {
    const params = new URLSearchParams();
    params.set("tab", "workflow");
    params.set("workflow_id", workflowId);
    if (taskId) params.set("task_id", taskId);
    window.location.href = `/${params.toString() ? `?${params.toString()}` : ""}`;
  };

  const handleCreate = async () => {
    if (!form.name.trim()) {
      setMessage("请先填写书名");
      return;
    }
    const chapters = form.chapters
      .split(/[,，\s]+/)
      .map((s) => parseInt(s, 10))
      .filter((n) => Number.isFinite(n) && n > 0);
    if (chapters.length === 0) {
      setMessage("章节列表格式不对，例如：1,2,3");
      return;
    }
    setBusy(true);
    try {
      const res = await fetch("/api/novel/pipelines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, chapters }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "创建失败");
      setProjects((prev) => [data.project, ...prev]);
      setSelectedId(data.project.project_id);
      setShowCreate(false);
      setForm(EMPTY_FORM);
      setMessage("小说项目已创建，可以开始连跑了");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  };

  const handleRun = async (reset: boolean) => {
    if (!selected) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/novel/pipelines/${selected.project_id}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reset }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "启动失败");
      setMessage(reset ? "已从头开始一键连跑" : "已从断点继续连跑");
      await fetchProjects();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "启动失败");
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await fetch(`/api/novel/pipelines/${selected.project_id}/stop`, { method: "POST" });
      setMessage("已停止连跑");
      await fetchProjects();
    } catch {
      setMessage("停止失败");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!selected) return;
    if (!window.confirm(`确认删除《${selected.name}》？项目文件会一并删除，E 盘完整文本存档保留。`)) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/novel/pipelines/${selected.project_id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("删除失败");
      setProjects((prev) => prev.filter((p) => p.project_id !== selected.project_id));
      setSelectedId(null);
      setMessage("已删除");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  };

  const openText = async () => {
    if (!selected) return;
    try {
      const res = await fetch(`/api/novel/pipelines/${selected.project_id}/text`);
      if (!res.ok) throw new Error("完整文本尚未生成");
      const data = await res.json();
      setTextModal({ name: data.name, content: data.content, path: data.path, archive: data.archive_path || "" });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "读取完整文本失败");
    }
  };

  const loadFiles = async () => {
    if (!selected) return;
    try {
      const res = await fetch(`/api/novel/pipelines/${selected.project_id}/files`);
      const data = await res.json();
      setFiles(data.files || []);
      setFilesOpen(true);
    } catch {
      setMessage("读取项目文件失败");
    }
  };

  const statusIcon = (status: string) => {
    const meta = STATUS_META[status] || STATUS_META.pending;
    const Icon = meta.icon;
    return <Icon size={16} className={meta.cls} aria-hidden="true" />;
  };

  const statusText = (status: string) => STATUS_META[status]?.label || status;

  return (
    <div className="h-[calc(100dvh-3.5rem)] flex flex-col bg-slate-950 text-slate-200">
      {/* 顶部 */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-white/5 shrink-0">
        <div className="flex items-center gap-3">
          <BookOpenText size={18} className="text-amber-400" aria-hidden="true" />
          <h2 className="text-lg font-semibold text-slate-100">小说管线</h2>
          <span className="text-xs text-slate-500">
            世界观 → 角色 → 故事规划 → 卷纲近纲 → 逐章生产/后验/润色 → 完整文本，全自动连跑
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowCreate((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 px-3 py-2 text-sm font-medium text-white transition-colors"
          >
            <Plus size={16} aria-hidden="true" /> 新建小说
          </button>
        </div>
      </div>

      {/* 新建表单 */}
      {showCreate && (
        <div className="px-6 py-4 border-b border-white/5 bg-slate-900/60 shrink-0 max-h-[45%] overflow-y-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs text-slate-400">书名 *</span>
              <input
                className="mt-1 w-full rounded-md border border-white/10 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-amber-500"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="例如：剑起沧澜"
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">类型</span>
              <input
                className="mt-1 w-full rounded-md border border-white/10 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-amber-500"
                value={form.genre}
                onChange={(e) => setForm({ ...form, genre: e.target.value })}
                placeholder="东方玄幻 / 都市异能 / 科幻末世…"
              />
            </label>
            <label className="block md:col-span-2">
              <span className="text-xs text-slate-400">故事创意（前提）</span>
              <textarea
                className="mt-1 w-full rounded-md border border-white/10 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-amber-500"
                rows={3}
                value={form.premise}
                onChange={(e) => setForm({ ...form, premise: e.target.value })}
                placeholder="描述主角、核心冲突、想要的味道…"
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">章节列表（逗号分隔）</span>
              <input
                className="mt-1 w-full rounded-md border border-white/10 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-amber-500"
                value={form.chapters}
                onChange={(e) => setForm({ ...form, chapters: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">每章目标字数</span>
              <input
                className="mt-1 w-full rounded-md border border-white/10 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-amber-500"
                value={form.target_word_count}
                onChange={(e) => setForm({ ...form, target_word_count: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">篇幅（短/中/长）</span>
              <input
                className="mt-1 w-full rounded-md border border-white/10 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-amber-500"
                value={form.estimated_length}
                onChange={(e) => setForm({ ...form, estimated_length: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">输出语言</span>
              <input
                className="mt-1 w-full rounded-md border border-white/10 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-amber-500"
                value={form.language}
                onChange={(e) => setForm({ ...form, language: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">写手模式</span>
              <select
                className="mt-1 w-full rounded-md border border-white/10 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-amber-500"
                value={form.writer_type}
                onChange={(e) => setForm({ ...form, writer_type: e.target.value })}
              >
                <option value="single">单写手（整章一次成文）</option>
                <option value="multi">多写手（骨架+对话+动作+内心分工）</option>
              </select>
            </label>
            <label className="block md:col-span-2">
              <span className="text-xs text-slate-400">人类意图（每章剧情走向，可选）</span>
              <textarea
                className="mt-1 w-full rounded-md border border-white/10 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-amber-500"
                rows={2}
                value={form.human_intent}
                onChange={(e) => setForm({ ...form, human_intent: e.target.value })}
                placeholder="例如：主角在第三章遭遇背叛，必须离开宗门…"
              />
            </label>
            <label className="block md:col-span-2">
              <span className="text-xs text-slate-400">世界意图（世界级推力，可选）</span>
              <textarea
                className="mt-1 w-full rounded-md border border-white/10 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-amber-500"
                rows={2}
                value={form.world_intent}
                onChange={(e) => setForm({ ...form, world_intent: e.target.value })}
                placeholder="例如：第三章时北方魔宗大举南下…"
              />
            </label>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              onClick={handleCreate}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-50"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
              创建项目
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(false)}
              className="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800 transition-colors"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {message && (
        <div className="px-6 py-2 bg-amber-500/10 border-b border-amber-500/20 text-sm text-amber-300 shrink-0 flex items-center justify-between">
          <span>{message}</span>
          <button type="button" onClick={() => setMessage(null)} className="text-amber-400 hover:text-amber-200">✕</button>
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {/* 左侧：项目列表 */}
        <aside className="w-64 shrink-0 border-r border-white/5 overflow-y-auto">
          <div className="px-4 py-2 text-xs text-slate-500 flex items-center justify-between">
            <span>项目（{projects.length}）</span>
            <button type="button" onClick={fetchProjects} aria-label="刷新列表" className="text-slate-500 hover:text-slate-200">
              <RefreshCw size={13} aria-hidden="true" />
            </button>
          </div>
          {loading ? (
            <div className="p-4 text-sm text-slate-500">加载中…</div>
          ) : projects.length === 0 ? (
            <div className="p-4 text-sm text-slate-500">还没有小说项目，点右上角「新建小说」开始。</div>
          ) : (
            projects.map((p) => (
              <button
                key={p.project_id}
                type="button"
                onClick={() => setSelectedId(p.project_id)}
                className={`w-full text-left px-4 py-3 border-b border-white/5 transition-colors ${selectedId === p.project_id ? "bg-amber-500/10" : "hover:bg-slate-900"}`}
              >
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium text-slate-100">《{p.name}》</span>
                  {p.status === "running" && <Loader2 size={13} className="text-amber-400 animate-spin shrink-0" aria-hidden="true" />}
                </div>
                <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                  <span>{p.chapters.length} 章</span>
                  <span>·</span>
                  <span>{p.status === "running" ? "连跑中" : p.status === "completed" ? "已完成" : p.status === "failed" ? "失败" : p.status === "stopped" ? "已停止" : "待开始"}</span>
                </div>
              </button>
            ))
          )}
        </aside>

        {/* 右侧：项目详情 */}
        <main className="flex-1 min-w-0 overflow-y-auto">
          {!selected ? (
            <div className="h-full flex items-center justify-center text-slate-500 text-sm">
              选择左侧项目查看详情，或新建一部小说
            </div>
          ) : (
            <div className="p-6 space-y-5">
              {/* 项目信息 */}
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-xl font-semibold text-slate-100">《{selected.name}》</h3>
                  <p className="mt-1 text-sm text-slate-400">
                    {selected.genre || "未设置类型"} · {selected.language} · 章节 {selected.chapters.join("、")}
                  </p>
                  {selected.premise && (
                    <p className="mt-2 max-w-3xl text-sm text-slate-400 whitespace-pre-wrap">{selected.premise}</p>
                  )}
                  {selected.error && (
                    <p className="mt-2 text-sm text-red-400">错误：{selected.error}</p>
                  )}
                  {selected.status === "completed" && (
                    <p className="mt-2 text-sm text-emerald-400">✅ 全书已生成，E 盘存档：{selected.archive_path || "—"}</p>
                  )}
                  {selected.status === "running" && (
                    <p className="mt-2 text-sm text-amber-400 flex items-center gap-2">
                      <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                      正在连跑：{selected.steps.find((s) => s.key === selected.current_step)?.label || selected.current_step || "准备中"}
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={busy || selected.status === "running"}
                    onClick={() => handleRun(false)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-sm font-medium text-white transition-colors disabled:opacity-50"
                  >
                    <Play size={15} aria-hidden="true" /> 继续连跑
                  </button>
                  <button
                    type="button"
                    disabled={busy || selected.status === "running"}
                    onClick={() => handleRun(true)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 px-3 py-2 text-sm font-medium text-white transition-colors disabled:opacity-50"
                  >
                    <RotateCcw size={15} aria-hidden="true" /> 从头连跑
                  </button>
                  <button
                    type="button"
                    disabled={busy || selected.status !== "running"}
                    onClick={handleStop}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/40 text-red-300 hover:bg-red-500/10 px-3 py-2 text-sm transition-colors disabled:opacity-50"
                  >
                    <Square size={15} aria-hidden="true" /> 停止
                  </button>
                  <button
                    type="button"
                    onClick={openText}
                    disabled={!selected.final_text_path && selected.status !== "completed"}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 transition-colors disabled:opacity-40"
                  >
                    <FileText size={15} aria-hidden="true" /> 完整文本
                  </button>
                  {selected.final_text_path && (
                    <a
                      href={`/api/novel/pipelines/${selected.project_id}/text/download`}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 transition-colors"
                    >
                      <Download size={15} aria-hidden="true" /> 下载
                    </a>
                  )}
                  <button
                    type="button"
                    onClick={loadFiles}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 transition-colors"
                  >
                    <FolderOpen size={15} aria-hidden="true" /> 项目文件
                  </button>
                  <button
                    type="button"
                    onClick={handleDelete}
                    disabled={busy || selected.status === "running"}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-400 hover:text-red-300 hover:border-red-500/40 transition-colors disabled:opacity-40"
                  >
                    <Trash2 size={15} aria-hidden="true" />
                  </button>
                </div>
              </div>

              {/* 存储路径 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                <div className="rounded-lg border border-white/5 bg-slate-900/60 px-3 py-2">
                  <span className="text-slate-500">工作区（子工作流共享）：</span>
                  <code className="ml-1 break-all text-slate-300">{selected.workspace}</code>
                </div>
                <div className="rounded-lg border border-white/5 bg-slate-900/60 px-3 py-2">
                  <span className="text-slate-500">E 盘存档：</span>
                  <code className="ml-1 break-all text-slate-300">{selected.archive_path || "E:\\故事机器\\小说存档\\《书名》\\（完成后生成）"}</code>
                </div>
              </div>

              {/* 流水线步骤 */}
              <section>
                <h4 className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-300">
                  <span className="h-2 w-2 rounded-full bg-amber-400" aria-hidden="true" />
                  流水线（自动串联，完成一个自动进入下一个）
                </h4>
                <ol className="space-y-2">
                  {selected.steps.map((step, idx) => {
                    const meta = STATUS_META[step.status] || STATUS_META.pending;
                    const isChapter = step.key.startsWith("chapter-");
                    return (
                      <li key={step.key} className="flex items-center gap-3 rounded-lg border border-white/5 bg-slate-900/40 px-3 py-2.5">
                        <span className="w-6 shrink-0 text-center text-xs text-slate-600">{idx + 1}</span>
                        {statusIcon(step.status)}
                        <div className="flex-1 min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`text-sm ${isChapter ? "text-slate-300" : "font-medium text-slate-200"}`}>{step.label}</span>
                            <span className="rounded bg-white/5 px-1.5 py-0.5 text-[11px] text-slate-400">
                              {workflowName(step.workflow_id)}
                            </span>
                            <span className={`text-xs ${meta.cls.replace("animate-spin", "")}`}>{statusText(step.status)}</span>
                          </div>
                          {step.error && <p className="mt-1 text-xs text-red-400 break-words">{step.error}</p>}
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => openWorkflow(step.workflow_id, step.task_id || undefined)}
                            className="inline-flex items-center gap-1 rounded-md border border-white/10 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 transition-colors"
                            title={step.task_id ? "打开该步骤的任务（可查看/修改节点）" : "打开工作流模板"}
                          >
                            <ExternalLink size={12} aria-hidden="true" />
                            {step.task_id ? "查看任务" : "查看工作流"}
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </section>
            </div>
          )}
        </main>
      </div>

      {/* 完整文本弹窗 */}
      {textModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true">
          <div className="flex h-[85vh] w-full max-w-4xl flex-col rounded-xl border border-white/10 bg-slate-900 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-3 shrink-0">
              <div>
                <h3 className="text-base font-semibold text-slate-100">《{textModal.name}》完整文本</h3>
                <p className="mt-0.5 text-xs text-slate-500 break-all">{textModal.path}</p>
                {textModal.archive && <p className="text-xs text-emerald-400/80 break-all">E 盘存档：{textModal.archive}</p>}
              </div>
              <div className="flex items-center gap-2">
                <a
                  href={`/api/novel/pipelines/${selected?.project_id}/text/download`}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 px-3 py-1.5 text-sm text-white transition-colors"
                >
                  <Download size={14} aria-hidden="true" /> 下载
                </a>
                <button
                  type="button"
                  onClick={() => setTextModal(null)}
                  className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
                >
                  关闭
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-4">
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-200">{textModal.content}</pre>
            </div>
          </div>
        </div>
      )}

      {/* 项目文件弹窗 */}
      {filesOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true">
          <div className="flex h-[70vh] w-full max-w-2xl flex-col rounded-xl border border-white/10 bg-slate-900 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-3 shrink-0">
              <h3 className="text-base font-semibold text-slate-100">项目产出文件（工作区内）</h3>
              <button type="button" onClick={() => setFilesOpen(false)} className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800">
                关闭
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-3">
              {files.length === 0 ? (
                <p className="text-sm text-slate-500">还没有产出文件，开始连跑后这里会出现世界观/大纲/章节等。</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-500">
                      <th className="pb-2 font-normal">文件</th>
                      <th className="pb-2 font-normal">大小</th>
                    </tr>
                  </thead>
                  <tbody>
                    {files.map((f) => (
                      <tr key={f.path} className="border-t border-white/5">
                        <td className="py-1.5 pr-3 break-all text-slate-300">{f.path}</td>
                        <td className="py-1.5 text-slate-500">{f.size > 1024 ? `${(f.size / 1024).toFixed(1)} KB` : `${f.size} B`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 连接状态指示 */}
      {connected && (
        <div className="fixed bottom-4 right-4 z-40 flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 px-3 py-1.5 text-xs text-emerald-300">
          <Loader2 size={12} className="animate-spin" aria-hidden="true" /> 连跑中，实时更新…
        </div>
      )}
    </div>
  );
}
