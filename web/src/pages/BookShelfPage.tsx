/**
 * 书架 + 作品工作台：
 * 书架（作品列表/新建）→ 进书后 7 个分页（总览/世界观/角色/大纲章节/演绎/流水线/工作流）。
 * 第一迭代为静态关联：书里能看到角色、演绎记录、章节，不做动态闭环。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpenText, Plus, Play, RotateCcw, Square, Download,
  FolderOpen, FileText, ArrowLeft, Loader2, Trash2, CheckCircle2,
  XCircle, Circle, ExternalLink, Sparkles, UserPlus, Theater, BookMarked,
  Globe2, ListTree, Workflow as WorkflowIcon, LayoutGrid, Users,
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
  world_id: string;
  character_ids: string[];
  theater_session_ids: string[];
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

interface Character {
  character_id: string;
  name: string;
  base_ratio: Record<string, number>;
  ratio_descriptions: Record<string, string>;
  types: string[];
  stats: Record<string, number>;
  abilities: { name: string; level: number }[];
  equipment: { name: string; effect: string; slot: string }[];
  traits: { name: string }[];
  summary: string;
  memory_logs: unknown[];
}

interface TheaterSession {
  session_id: string;
  world_id: string;
  mode: string;
  title: string;
  character_ids: string[];
  scene: Record<string, unknown>;
  status: string;
  record: string[];
  created_at: string;
}

interface ChapterInfo {
  number: number;
  chapter_number: string;
  status: string;
  word_count: number;
}

interface ProjectContent {
  project: NovelProject;
  world: Record<string, unknown> | null;
  characters: Character[];
  outline: { volume_outline: string; near_term_outline: string };
  world_foundation: string;
  chapters: ChapterInfo[];
  theater_sessions: TheaterSession[];
  workspace: string;
  archive_path: string;
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

const STATUS_META: Record<string, { label: string; cls: string }> = {
  pending: { label: "等待", cls: "text-slate-500" },
  running: { label: "运行中", cls: "text-amber-400" },
  completed: { label: "完成", cls: "text-emerald-400" },
  failed: { label: "失败", cls: "text-red-400" },
};

const WORKFLOW_LINKS: { id: string; label: string; desc: string }[] = [
  { id: "bishu-novel-build", label: "世界观构建", desc: "六维世界规则 → world_foundation.md" },
  { id: "bishu-novel-character", label: "角色创建", desc: "骨架/信念/深层/声线 → 角色档案" },
  { id: "bishu-novel-story-plan", label: "故事宏观规划", desc: "故事引擎 + 风格档案" },
  { id: "bishu-novel-outline", label: "卷纲近纲规划", desc: "卷纲骨架 + 逐章简纲" },
  { id: "bishu-novel-mvp", label: "章节生产", desc: "世界状态机 → 意图 → 大纲 → 成文" },
  { id: "bishu-novel-post-hoc", label: "章节后验", desc: "伏笔/债务/一致性裁决" },
  { id: "bishu-novel-polish", label: "章节润色", desc: "自审 → 人文化 → 专业润色" },
];

function workflowName(id: string): string {
  return WORKFLOW_LINKS.find((w) => w.id === id)?.label || id;
}

const inputCls =
  "mt-1 w-full rounded-md border border-white/10 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-amber-500";

export default function BookShelfPage() {
  const [projects, setProjects] = useState<NovelProject[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  // 作品工作台状态
  const [tab, setTab] = useState("overview");
  const [content, setContent] = useState<ProjectContent | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [charPickerOpen, setCharPickerOpen] = useState(false);
  const [allChars, setAllChars] = useState<Character[]>([]);
  const [theaterForm, setTheaterForm] = useState({ title: "", scene: "", mode: "perform" });
  const [theaterOpen, setTheaterOpen] = useState(false);
  const [chapterModal, setChapterModal] = useState<{ number: number; content: string } | null>(null);
  const [textModal, setTextModal] = useState<{ name: string; content: string; path: string; archive: string } | null>(null);
  const [filesOpen, setFilesOpen] = useState(false);
  const [files, setFiles] = useState<{ path: string; size: number }[]>([]);

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
      setSelectedId((cur) => (cur && list.some((p) => p.project_id === cur) ? cur : (list[0]?.project_id ?? null)));
    } catch {
      setMessage("作品列表加载失败");
    }
  }, []);

  const fetchContent = useCallback(async (pid: string) => {
    setContentLoading(true);
    try {
      const res = await fetch(`/api/novel/pipelines/${pid}/content`);
      if (res.ok) setContent(await res.json());
    } catch {
      /* ignore */
    } finally {
      setContentLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  useEffect(() => {
    if (selectedId) {
      setContent(null);
      fetchContent(selectedId);
    } else {
      setContent(null);
    }
  }, [selectedId, fetchContent]);

  // 实时刷新：连跑过程每步推送 novel_pipeline_update
  useWebSocket({
    url: "/ws/events",
    autoConnect: true,
    onMessage: useCallback(
      (raw: unknown) => {
        const evt = raw as { type?: string; project_id?: string; status?: string };
        if (evt?.type !== "novel_pipeline_update") return;
        setConnected(true);
        fetchProjects();
        if (selectedId) fetchContent(selectedId);
        if (evt.status === "completed" || evt.status === "failed" || evt.status === "stopped") {
          setTimeout(() => setConnected(false), 3000);
        }
      },
      [fetchProjects, fetchContent, selectedId],
    ),
  });

  const openWorkflow = (workflowId: string, taskId?: string) => {
    const params = new URLSearchParams();
    params.set("tab", "workflow");
    params.set("workflow_id", workflowId);
    if (taskId) params.set("task_id", taskId);
    window.location.href = `/${params.toString() ? `?${params.toString()}` : ""}`;
  };

  const goTheater = () => {
    window.location.href = "/?tab=theater";
  };

  const showMsg = (m: string) => {
    setMessage(m);
    setTimeout(() => setMessage(null), 6000);
  };

  const handleCreate = async () => {
    if (!form.name.trim()) {
      showMsg("请先填写书名");
      return;
    }
    const chapters = form.chapters
      .split(/[,，\s]+/)
      .map((s) => parseInt(s, 10))
      .filter((n) => Number.isFinite(n) && n > 0);
    if (chapters.length === 0) {
      showMsg("章节列表格式不对，例如：1,2,3");
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
      setTab("overview");
      showMsg("作品已创建，可以去「角色」添加人物、「演绎」开一场戏、「流水线」连跑成书");
    } catch (e) {
      showMsg(e instanceof Error ? e.message : "创建失败");
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
      showMsg(reset ? "已从头开始一键连跑" : "已从断点继续连跑");
      await fetchProjects();
    } catch (e) {
      showMsg(e instanceof Error ? e.message : "启动失败");
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await fetch(`/api/novel/pipelines/${selected.project_id}/stop`, { method: "POST" });
      showMsg("已停止连跑");
      await fetchProjects();
    } catch {
      showMsg("停止失败");
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
      showMsg("已删除");
    } catch (e) {
      showMsg(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  };

  const openCharPicker = async () => {
    try {
      const res = await fetch("/api/characters");
      const data = await res.json();
      setAllChars(data.characters || []);
      setCharPickerOpen(true);
    } catch {
      showMsg("读取人物库失败");
    }
  };

  const addCharacter = async (cid: string) => {
    if (!selected) return;
    try {
      const res = await fetch(`/api/novel/pipelines/${selected.project_id}/characters`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character_id: cid }),
      });
      if (!res.ok) throw new Error("关联失败");
      await fetchContent(selected.project_id);
      setCharPickerOpen(false);
      showMsg("角色已加入作品");
    } catch (e) {
      showMsg(e instanceof Error ? e.message : "关联失败");
    }
  };

  const removeCharacter = async (cid: string) => {
    if (!selected) return;
    try {
      await fetch(`/api/novel/pipelines/${selected.project_id}/characters/${cid}`, { method: "DELETE" });
      await fetchContent(selected.project_id);
    } catch {
      showMsg("移除失败");
    }
  };

  const createTheater = async () => {
    if (!selected) return;
    if (!theaterForm.title.trim()) {
      showMsg("请填写演出标题");
      return;
    }
    setBusy(true);
    try {
      const scene = theaterForm.scene.trim()
        ? { text: theaterForm.scene.trim() }
        : {};
      const res = await fetch(`/api/novel/pipelines/${selected.project_id}/theater`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: theaterForm.title, scene, mode: theaterForm.mode }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "创建失败");
      await fetchContent(selected.project_id);
      setTheaterOpen(false);
      setTheaterForm({ title: "", scene: "", mode: "perform" });
      showMsg("演出已创建并挂到本书，去「剧场」页可继续演绎");
    } catch (e) {
      showMsg(e instanceof Error ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  };

  const openChapter = async (no: number) => {
    if (!selected) return;
    try {
      const res = await fetch(`/api/novel/pipelines/${selected.project_id}/chapters/${no}/text`);
      if (!res.ok) throw new Error("章节尚未生成");
      const data = await res.json();
      setChapterModal({ number: no, content: data.content });
    } catch (e) {
      showMsg(e instanceof Error ? e.message : "读取章节失败");
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
      showMsg(e instanceof Error ? e.message : "读取完整文本失败");
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
      showMsg("读取项目文件失败");
    }
  };

  const statusIcon = (status: string) => {
    const map: Record<string, typeof Circle> = {
      pending: Circle,
      running: Loader2,
      completed: CheckCircle2,
      failed: XCircle,
    };
    const Icon = map[status] || Circle;
    const cls = STATUS_META[status]?.cls || "text-slate-500";
    return <Icon size={16} className={`${cls} ${status === "running" ? "animate-spin" : ""}`} aria-hidden="true" />;
  };

  const TABS = [
    { id: "overview", label: "总览", icon: LayoutGrid },
    { id: "world", label: "世界观", icon: Globe2 },
    { id: "cast", label: "角色", icon: Users },
    { id: "outline", label: "大纲章节", icon: ListTree },
    { id: "theater", label: "演绎", icon: Theater },
    { id: "pipeline", label: "流水线", icon: BookMarked },
    { id: "workflow", label: "工作流", icon: WorkflowIcon },
  ];

  // ==================== 分页内容 ====================

  const renderOverview = () => {
    if (!selected) return null;
    const chaptersDone = (content?.chapters || []).filter((c) => c.status === "已生成").length;
    const theaterCount = content?.theater_sessions?.length || 0;
    const charCount = content?.characters?.length || 0;
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { k: "章节", v: `${chaptersDone} / ${selected.chapters.length}` },
            { k: "角色", v: String(charCount) },
            { k: "演绎记录", v: String(theaterCount) },
            { k: "状态", v: selected.status === "running" ? "连跑中" : selected.status === "completed" ? "已完成" : selected.status === "failed" ? "失败" : selected.status === "stopped" ? "已停止" : "待开始" },
          ].map((x) => (
            <div key={x.k} className="rounded-lg border border-white/5 bg-slate-900/60 px-4 py-3">
              <div className="text-xs text-slate-500">{x.k}</div>
              <div className="mt-1 text-lg font-semibold text-slate-100">{x.v}</div>
            </div>
          ))}
        </div>
        <div className="rounded-lg border border-white/5 bg-slate-900/60 p-4">
          <div className="text-sm font-medium text-slate-200">创意</div>
          <p className="mt-1 text-sm text-slate-400 whitespace-pre-wrap">{selected.premise || "（未填写）"}</p>
        </div>
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
      </div>
    );
  };

  const renderWorld = () => {
    const wf = content?.world_foundation || "";
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-400">
            流水线世界观产出（{wf ? `${wf.length} 字` : "尚未生成"}）· 第一版只读
          </p>
          {content?.world && (
            <span className="rounded bg-white/5 px-2 py-0.5 text-xs text-slate-400">
              剧场世界：{(content.world as { name?: string }).name || "未命名"}
            </span>
          )}
        </div>
        {wf ? (
          <pre className="whitespace-pre-wrap rounded-lg border border-white/5 bg-slate-900/60 p-4 text-sm leading-relaxed text-slate-200 max-h-[60vh] overflow-y-auto">
            {wf}
          </pre>
        ) : (
          <div className="rounded-lg border border-dashed border-white/10 p-8 text-center text-sm text-slate-500">
            世界观尚未生成。去「流水线」页跑一次「世界观构建」，这里就会展示六维世界规则。
          </div>
        )}
      </div>
    );
  };

  const renderCast = () => {
    const chars = content?.characters || [];
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-400">这本书关联的人物库角色（{chars.length}）</p>
          <button
            type="button"
            onClick={openCharPicker}
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 px-3 py-1.5 text-sm text-white transition-colors"
          >
            <UserPlus size={15} aria-hidden="true" /> 从人物库添加
          </button>
        </div>
        {chars.length === 0 ? (
          <div className="rounded-lg border border-dashed border-white/10 p-8 text-center text-sm text-slate-500">
            还没有角色。点右上角「从人物库添加」，选几个人物进这本书。
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {chars.map((c) => (
              <div key={c.character_id} className="rounded-lg border border-white/5 bg-slate-900/60 p-4">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-medium text-slate-100">{c.name}</div>
                    <div className="mt-0.5 text-xs text-slate-500">
                      {(c.types || []).join(" · ") || "未分类"}　{(c.summary || "").slice(0, 60)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeCharacter(c.character_id)}
                    className="text-slate-500 hover:text-red-300"
                    title="移出本书"
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  {(Object.entries(c.base_ratio || {})).map(([k, v]) => (
                    <span key={k} className="rounded bg-white/5 px-2 py-0.5 text-slate-300">
                      {k === "id" ? "本我" : k === "ego" ? "自我" : "超我"} {v}%
                    </span>
                  ))}
                  {(Object.entries(c.stats || {})).slice(0, 5).map(([k, v]) => (
                    <span key={k} className="rounded bg-white/5 px-2 py-0.5 text-slate-400">
                      {k} {v}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const renderOutline = () => {
    const chapters = content?.chapters || [];
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {[
            { title: "卷纲", text: content?.outline?.volume_outline || "" },
            { title: "近纲", text: content?.outline?.near_term_outline || "" },
          ].map((o) => (
            <div key={o.title} className="rounded-lg border border-white/5 bg-slate-900/60 p-3">
              <div className="text-sm font-medium text-slate-200">{o.title}</div>
              <pre className="mt-2 whitespace-pre-wrap text-xs text-slate-400 max-h-48 overflow-y-auto">
                {o.text || "（尚未生成，跑「流水线」的卷纲近纲规划后出现）"}
              </pre>
            </div>
          ))}
        </div>
        <div>
          <div className="mb-2 text-sm font-medium text-slate-300">章节</div>
          {chapters.length === 0 ? (
            <div className="rounded-lg border border-dashed border-white/10 p-6 text-center text-sm text-slate-500">
              还没有章节，去「流水线」一键连跑生成。
            </div>
          ) : (
            <div className="space-y-2">
              {chapters.map((ch) => (
                <div key={ch.number} className="flex items-center gap-3 rounded-lg border border-white/5 bg-slate-900/40 px-3 py-2">
                  <span className="w-16 shrink-0 text-sm text-slate-300">第 {ch.number} 章</span>
                  <span className={`rounded px-2 py-0.5 text-xs ${ch.status === "已生成" ? "bg-emerald-500/10 text-emerald-300" : "bg-white/5 text-slate-500"}`}>
                    {ch.status}
                  </span>
                  {ch.word_count > 0 && <span className="text-xs text-slate-500">{ch.word_count} 字</span>}
                  <div className="flex-1" />
                  <button
                    type="button"
                    disabled={ch.status !== "已生成"}
                    onClick={() => openChapter(ch.number)}
                    className="inline-flex items-center gap-1 rounded-md border border-white/10 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
                  >
                    <FileText size={12} aria-hidden="true" /> 查看正文
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderTheater = () => {
    const sessions = content?.theater_sessions || [];
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm text-slate-400">这本书的剧场演绎记录（{sessions.length}）</p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={goTheater}
              className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800 transition-colors"
            >
              去剧场页
            </button>
            <button
              type="button"
              onClick={() => setTheaterOpen((v) => !v)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 px-3 py-1.5 text-sm text-white transition-colors"
            >
              <Plus size={15} aria-hidden="true" /> 新开演绎
            </button>
          </div>
        </div>
        {theaterOpen && (
          <div className="rounded-lg border border-white/10 bg-slate-900/70 p-4 space-y-3">
            <div className="text-sm font-medium text-slate-200">新开一场演绎（用本书角色 + 本书世界）</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs text-slate-400">演出标题 *</span>
                <input
                  className={inputCls}
                  value={theaterForm.title}
                  onChange={(e) => setTheaterForm({ ...theaterForm, title: e.target.value })}
                  placeholder="例如：宗门夜谈"
                />
              </label>
              <label className="block">
                <span className="text-xs text-slate-400">模式</span>
                <select
                  className={inputCls}
                  value={theaterForm.mode}
                  onChange={(e) => setTheaterForm({ ...theaterForm, mode: e.target.value })}
                >
                  <option value="perform">演绎（角色开演）</option>
                  <option value="discuss">讨论（剧情会商）</option>
                </select>
              </label>
            </div>
            <label className="block">
              <span className="text-xs text-slate-400">场景描述（可选）</span>
              <textarea
                className={inputCls}
                rows={2}
                value={theaterForm.scene}
                onChange={(e) => setTheaterForm({ ...theaterForm, scene: e.target.value })}
                placeholder="例如：雨夜，破庙，三人对峙"
              />
            </label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={createTheater}
                className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 px-3 py-1.5 text-sm text-white disabled:opacity-50"
              >
                <Theater size={14} aria-hidden="true" /> 创建并挂到本书
              </button>
              <button
                type="button"
                onClick={() => setTheaterOpen(false)}
                className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
              >
                取消
              </button>
            </div>
          </div>
        )}
        {sessions.length === 0 ? (
          <div className="rounded-lg border border-dashed border-white/10 p-8 text-center text-sm text-slate-500">
            还没有演绎记录。点「新开演绎」，用本书角色在世界里演一场，之后每场戏都会出现在这里。
          </div>
        ) : (
          <div className="space-y-2">
            {sessions.map((s) => (
              <div key={s.session_id} className="flex items-center gap-3 rounded-lg border border-white/5 bg-slate-900/40 px-3 py-2.5">
                <span className={`h-2 w-2 shrink-0 rounded-full ${s.status === "ended" ? "bg-slate-600" : "bg-amber-400"}`} aria-hidden="true" />
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-slate-200">{s.title}</span>
                    <span className="rounded bg-white/5 px-1.5 py-0.5 text-[11px] text-slate-400">
                      {s.mode === "discuss" ? "讨论" : "演绎"}
                    </span>
                    <span className="text-[11px] text-slate-500">{s.record?.length || 0} 条记录</span>
                  </div>
                  {s.scene && (s.scene as { text?: string }).text && (
                    <div className="mt-0.5 truncate text-xs text-slate-500">场景：{(s.scene as { text: string }).text}</div>
                  )}
                </div>
                <span className="shrink-0 text-xs text-slate-500">{String(s.created_at || "").slice(0, 16).replace("T", " ")}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const renderPipeline = () => {
    if (!selected) return null;
    const steps = selected.steps || [];
    return (
      <div className="space-y-4">
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
        </div>
        {selected.error && (
          <p className="text-sm text-red-400">错误：{selected.error}</p>
        )}
        {selected.status === "running" && (
          <p className="text-sm text-amber-400 flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
            正在连跑：{steps.find((s) => s.key === selected.current_step)?.label || selected.current_step || "准备中"}
          </p>
        )}
        <ol className="space-y-2">
          {steps.map((step, idx) => {
            const isChapter = step.key.startsWith("chapter-");
            return (
              <li key={step.key} className="flex items-center gap-3 rounded-lg border border-white/5 bg-slate-900/40 px-3 py-2.5">
                <span className="w-6 shrink-0 text-center text-xs text-slate-600">{idx + 1}</span>
                {statusIcon(step.status)}
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`text-sm ${isChapter ? "text-slate-300" : "font-medium text-slate-200"}`}>{step.label}</span>
                    <span className="rounded bg-white/5 px-1.5 py-0.5 text-[11px] text-slate-400">{workflowName(step.workflow_id)}</span>
                    <span className={`text-xs ${STATUS_META[step.status]?.cls || ""}`}>{STATUS_META[step.status]?.label || step.status}</span>
                  </div>
                  {step.error && <p className="mt-1 text-xs text-red-400 break-words">{step.error}</p>}
                </div>
                <button
                  type="button"
                  onClick={() => openWorkflow(step.workflow_id, step.task_id || undefined)}
                  className="inline-flex shrink-0 items-center gap-1 rounded-md border border-white/10 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 transition-colors"
                  title={step.task_id ? "打开该步骤的任务" : "打开工作流模板"}
                >
                  <ExternalLink size={12} aria-hidden="true" />
                  {step.task_id ? "查看任务" : "查看工作流"}
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    );
  };

  const renderWorkflow = () => (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">
        这本书背后的 7 个写作工作流（笔枢同款管线）。点开可查看/修改节点，改完再跑即生效。
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {WORKFLOW_LINKS.map((w) => (
          <button
            key={w.id}
            type="button"
            onClick={() => openWorkflow(w.id)}
            className="flex items-center gap-3 rounded-lg border border-white/5 bg-slate-900/60 p-4 text-left hover:bg-slate-900 transition-colors"
          >
            <WorkflowIcon size={18} className="shrink-0 text-purple-400" aria-hidden="true" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-slate-100">{w.label}</div>
              <div className="mt-0.5 text-xs text-slate-500">{w.desc}</div>
            </div>
            <ExternalLink size={14} className="shrink-0 text-slate-500" aria-hidden="true" />
          </button>
        ))}
      </div>
    </div>
  );

  // ==================== 书架视图 ====================

  const renderShelf = () => (
    <div className="flex-1 min-h-0 overflow-y-auto p-6">
      {projects.length === 0 && !loading ? (
        <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
          <BookOpenText size={40} className="text-slate-600" aria-hidden="true" />
          <p className="text-sm text-slate-500">还没有作品，点右上角「新建作品」开始第一本书。</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((p) => (
            <button
              key={p.project_id}
              type="button"
              onClick={() => {
                setSelectedId(p.project_id);
                setTab("overview");
              }}
              className="group rounded-xl border border-white/5 bg-slate-900/60 p-5 text-left hover:border-amber-500/30 hover:bg-slate-900 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-lg font-semibold text-slate-100">《{p.name}》</div>
                  <div className="mt-1 text-xs text-slate-500">{p.genre || "未设置类型"} · {p.language}</div>
                </div>
                {p.status === "running" && <Loader2 size={16} className="shrink-0 text-amber-400 animate-spin" aria-hidden="true" />}
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <span className="rounded bg-white/5 px-2 py-0.5 text-slate-400">{p.chapters.length} 章</span>
                <span className="rounded bg-white/5 px-2 py-0.5 text-slate-400">{p.character_ids.length} 角色</span>
                <span className="rounded bg-white/5 px-2 py-0.5 text-slate-400">{p.theater_session_ids.length} 演绎</span>
                <span
                  className={`rounded px-2 py-0.5 ${
                    p.status === "running"
                      ? "bg-amber-500/10 text-amber-300"
                      : p.status === "completed"
                        ? "bg-emerald-500/10 text-emerald-300"
                        : p.status === "failed"
                          ? "bg-red-500/10 text-red-300"
                          : "bg-white/5 text-slate-400"
                  }`}
                >
                  {p.status === "running" ? "连跑中" : p.status === "completed" ? "已完成" : p.status === "failed" ? "失败" : p.status === "stopped" ? "已停止" : "待开始"}
                </span>
              </div>
              <div className="mt-3 text-xs text-slate-500">
                {(p.premise || "（无创意描述）").slice(0, 80)}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className="h-[calc(100dvh-3.5rem)] flex flex-col bg-slate-950 text-slate-200">
      {/* 顶部 */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-white/5 shrink-0">
        <div className="flex items-center gap-3">
          {selected ? (
            <button
              type="button"
              onClick={() => {
                setSelectedId(null);
                setContent(null);
                setTab("overview");
              }}
              className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-100"
            >
              <ArrowLeft size={15} aria-hidden="true" /> 书架
            </button>
          ) : (
            <BookOpenText size={18} className="text-amber-400" aria-hidden="true" />
          )}
          <h2 className="text-lg font-semibold text-slate-100">
            {selected ? `《${selected.name}》` : "书架"}
          </h2>
          {selected && (
            <span className="text-xs text-slate-500">
              作品工作台 · {TABS.find((t) => t.id === tab)?.label || ""}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {selected && (
            <button
              type="button"
              onClick={handleDelete}
              disabled={busy || selected.status === "running"}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-400 hover:text-red-300 hover:border-red-500/40 transition-colors disabled:opacity-40"
              title="删除作品"
            >
              <Trash2 size={15} aria-hidden="true" />
            </button>
          )}
          <button
            type="button"
            onClick={() => setShowCreate((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 px-3 py-2 text-sm font-medium text-white transition-colors"
          >
            <Plus size={16} aria-hidden="true" /> 新建作品
          </button>
        </div>
      </div>

      {/* 新建表单 */}
      {showCreate && !selected && (
        <div className="px-6 py-4 border-b border-white/5 bg-slate-900/60 shrink-0 max-h-[45%] overflow-y-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs text-slate-400">书名 *</span>
              <input
                className={inputCls}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="例如：剑起沧澜"
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">类型</span>
              <input
                className={inputCls}
                value={form.genre}
                onChange={(e) => setForm({ ...form, genre: e.target.value })}
                placeholder="东方玄幻 / 都市异能 / 科幻末世…"
              />
            </label>
            <label className="block md:col-span-2">
              <span className="text-xs text-slate-400">故事创意（前提）</span>
              <textarea
                className={inputCls}
                rows={3}
                value={form.premise}
                onChange={(e) => setForm({ ...form, premise: e.target.value })}
                placeholder="描述主角、核心冲突、想要的味道…"
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">章节列表（逗号分隔）</span>
              <input
                className={inputCls}
                value={form.chapters}
                onChange={(e) => setForm({ ...form, chapters: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">每章目标字数</span>
              <input
                className={inputCls}
                value={form.target_word_count}
                onChange={(e) => setForm({ ...form, target_word_count: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">篇幅（短/中/长）</span>
              <input
                className={inputCls}
                value={form.estimated_length}
                onChange={(e) => setForm({ ...form, estimated_length: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">输出语言</span>
              <input
                className={inputCls}
                value={form.language}
                onChange={(e) => setForm({ ...form, language: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="text-xs text-slate-400">写手模式</span>
              <select
                className={inputCls}
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
                className={inputCls}
                rows={2}
                value={form.human_intent}
                onChange={(e) => setForm({ ...form, human_intent: e.target.value })}
                placeholder="例如：主角在第三章遭遇背叛，必须离开宗门…"
              />
            </label>
            <label className="block md:col-span-2">
              <span className="text-xs text-slate-400">世界意图（世界级推力，可选）</span>
              <textarea
                className={inputCls}
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
              创建作品
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

      {/* 作品工作台 */}
      {selected ? (
        <div className="flex-1 flex min-h-0">
          <nav className="w-44 shrink-0 border-r border-white/5 overflow-y-auto py-2" aria-label="作品分页">
            {TABS.map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTab(t.id)}
                  className={`w-full flex items-center gap-2 px-4 py-2.5 text-left text-sm transition-colors ${
                    tab === t.id ? "bg-amber-500/10 text-amber-300 border-r-2 border-amber-500" : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
                  }`}
                >
                  <Icon size={15} aria-hidden="true" />
                  {t.label}
                </button>
              );
            })}
          </nav>
          <main className="flex-1 min-w-0 overflow-y-auto">
            <div className="p-6">
              {contentLoading && !content ? (
                <div className="flex items-center justify-center py-16 text-sm text-slate-500">
                  <Loader2 size={16} className="animate-spin mr-2" aria-hidden="true" /> 加载作品内容…
                </div>
              ) : (
                <>
                  {tab === "overview" && renderOverview()}
                  {tab === "world" && renderWorld()}
                  {tab === "cast" && renderCast()}
                  {tab === "outline" && renderOutline()}
                  {tab === "theater" && renderTheater()}
                  {tab === "pipeline" && renderPipeline()}
                  {tab === "workflow" && renderWorkflow()}
                </>
              )}
            </div>
          </main>
        </div>
      ) : (
        renderShelf()
      )}

      {/* 角色选择弹窗 */}
      {charPickerOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true">
          <div className="flex h-[70vh] w-full max-w-2xl flex-col rounded-xl border border-white/10 bg-slate-900 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-3 shrink-0">
              <h3 className="text-base font-semibold text-slate-100">从人物库添加角色</h3>
              <button type="button" onClick={() => setCharPickerOpen(false)} className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800">
                关闭
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-3">
              {allChars.length === 0 ? (
                <p className="text-sm text-slate-500">人物库还是空的，先去「人物库」页创建角色。</p>
              ) : (
                <div className="space-y-2">
                  {allChars.map((c) => {
                    const added = content?.project.character_ids.includes(c.character_id);
                    return (
                      <div key={c.character_id} className="flex items-center gap-3 rounded-lg border border-white/5 bg-slate-950/60 px-3 py-2.5">
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-slate-200">{c.name}</div>
                          <div className="text-xs text-slate-500">{(c.types || []).join(" · ") || "未分类"}</div>
                        </div>
                        <button
                          type="button"
                          disabled={added}
                          onClick={() => addCharacter(c.character_id)}
                          className="rounded-md border border-white/10 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
                        >
                          {added ? "已加入" : "加入本书"}
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 章节正文弹窗 */}
      {chapterModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true">
          <div className="flex h-[85vh] w-full max-w-3xl flex-col rounded-xl border border-white/10 bg-slate-900 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-3 shrink-0">
              <h3 className="text-base font-semibold text-slate-100">第 {chapterModal.number} 章 正文</h3>
              <button type="button" onClick={() => setChapterModal(null)} className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800">
                关闭
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-4">
              <pre className="whitespace-pre-wrap font-serif text-sm leading-relaxed text-slate-200">{chapterModal.content}</pre>
            </div>
          </div>
        </div>
      )}

      {/* 完整文本弹窗 */}
      {textModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true">
          <div className="flex h-[85vh] w-full max-w-4xl flex-col rounded-xl border border-white/10 bg-slate-900 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-3 shrink-0">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-slate-100">《{textModal.name}》完整文本</h3>
                <p className="mt-0.5 text-xs text-slate-500 break-all">{textModal.path}</p>
                {textModal.archive && <p className="text-xs text-emerald-400/80 break-all">E 盘存档：{textModal.archive}</p>}
              </div>
              <div className="flex items-center gap-2 shrink-0">
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

      {connected && (
        <div className="fixed bottom-4 right-4 z-40 flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 px-3 py-1.5 text-xs text-emerald-300">
          <Loader2 size={12} className="animate-spin" aria-hidden="true" /> 连跑中，实时更新…
        </div>
      )}
    </div>
  );
}
