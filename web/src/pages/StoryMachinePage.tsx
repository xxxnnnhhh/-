import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Clapperboard,
  Copy,
  Download,
  Pause,
  Play,
  Plus,
  Square,
} from "lucide-react";
import { Character, fetchCharacters } from "@/lib/characterApi";
import EntityModelSelect from "../components/EntityModelSelect";
import {
  StoryMessage,
  StorySessionDetail,
  StorySessionSummary,
  createStory,
  deleteStory,
  exportStory,
  fetchStoryDetail,
  fetchStories,
  injectStory,
  pauseStory,
  resumeStory,
  setStoryEmotion,
  startStory,
  stopStory,
} from "@/lib/storyApi";

const EMOTION_LABELS: Record<string, string> = {
  joy: "喜悦", trust: "信任", fear: "恐惧", surprise: "惊讶",
  sadness: "悲伤", disgust: "厌恶", anger: "愤怒", anticipation: "期待",
};

const STATUS_META: Record<string, { label: string; cls: string }> = {
  waiting: { label: "待开演", cls: "bg-slate-500/20 text-slate-400" },
  discussing: { label: "演出中", cls: "bg-green-500/20 text-green-400" },
  paused: { label: "已暂停", cls: "bg-amber-500/20 text-amber-400" },
  ended: { label: "已结束", cls: "bg-blue-500/20 text-blue-400" },
};

function Panel({ title, children, actions }: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/60 flex flex-col min-h-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/60">
        <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
        {actions}
      </div>
      <div className="p-3 overflow-y-auto min-h-0 flex-1 space-y-3">{children}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-slate-400 mb-1 block">{label}</span>
      {children}
    </label>
  );
}

const inputCls =
  "w-full bg-slate-800/80 border border-slate-700 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/60";

function CharacterLibraryPanel({
  characters,
}: {
  characters: Character[];
}) {
  return (
    <Panel
      title="人物库"
      actions={
        <a
          href="?tab=characters"
          className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700"
        >
          去编辑
        </a>
      }
    >
      <div className="text-xs text-slate-500">
        角色在「人物库」中创建与编辑，这里只负责选角。共 {characters.length} 个。
      </div>
      <div className="space-y-1.5">
        {characters.map((c) => (
          <div
            key={c.character_id}
            className="rounded-lg border border-slate-700/60 bg-slate-800/50 px-2.5 py-2"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-200">{c.name}</span>
              <span className="text-[10px] text-slate-500 font-mono">
                本{c.base_ratio.id} / 自{c.base_ratio.ego} / 超{c.base_ratio.superego}
              </span>
            </div>
            {c.traits.length > 0 && (
              <div className="text-[10px] text-slate-500 mt-0.5">
                {c.traits.map((t) => t.name).join("、")}
              </div>
            )}
          </div>
        ))}
        {characters.length === 0 && (
          <div className="text-xs text-slate-500 text-center py-6">
            人物库为空，请先到「人物库」Tab 创建角色
          </div>
        )}
      </div>
    </Panel>
  );
}

function TheaterPanel({
  characters,
  sessions,
  active,
  onActive,
  onSessionsChanged,
}: {
  characters: Character[];
  sessions: StorySessionSummary[];
  active: StorySessionDetail | null;
  onActive: (s: StorySessionDetail | null) => void;
  onSessionsChanged: () => void;
}) {
  const [title, setTitle] = useState("雨夜的谈判");
  const [location, setLocation] = useState("旧城区一家打烊的咖啡馆");
  const [time, setTime] = useState("深夜十一点");
  const [mood, setMood] = useState("压抑、潮湿");
  const [background, setBackground] = useState("");
  const [opening, setOpening] = useState("两人隔着桌子坐下，谁都没有先开口。");
  const [characterIds, setCharacterIds] = useState<string[]>([]);
  const [maxRounds, setMaxRounds] = useState(8);
  const [narrator, setNarrator] = useState(true);
  const [narratorModel, setNarratorModel] = useState<string | null>(null);
  const [injectText, setInjectText] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!title.trim() || characterIds.length === 0) return;
    setBusy(true);
    try {
      const res = await createStory({
        title,
        scene: { location, time, mood, background, opening },
        character_ids: characterIds,
        max_rounds: maxRounds,
        narrator_enabled: narrator,
        narrator_model: narratorModel,
      });
      onSessionsChanged();
      onActive(await fetchStoryDetail(res.session.session_id));
    } finally {
      setBusy(false);
    }
  };

  const toggleCharacter = (id: string) => {
    setCharacterIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const act = async (fn: () => Promise<unknown>) => {
    if (!active) return;
    setBusy(true);
    try {
      await fn();
      onActive(await fetchStoryDetail(active.session_id));
    } finally {
      setBusy(false);
    }
  };

  const status = active?.status ?? "waiting";

  return (
    <Panel
      title="剧场控制台"
      actions={
        active ? (
          <span className={`text-xs px-2 py-0.5 rounded ${STATUS_META[status]?.cls ?? ""}`}>
            {STATUS_META[status]?.label ?? status}
          </span>
        ) : undefined
      }
    >
      <div>
        <div className="flex flex-wrap gap-1.5 mb-2">
          {sessions.map((s) => (
            <button
              key={s.session_id}
              type="button"
              onClick={async () => onActive(await fetchStoryDetail(s.session_id))}
              className={`text-xs px-2.5 py-1 rounded border ${
                active?.session_id === s.session_id
                  ? "border-indigo-500/70 bg-indigo-500/15 text-indigo-300"
                  : "border-slate-700 bg-slate-800/70 text-slate-300"
              }`}
            >
              {s.title}
            </button>
          ))}
        </div>
        {active && (
          <button
            type="button"
            onClick={async () => {
              await deleteStory(active.session_id);
              onActive(null);
              onSessionsChanged();
            }}
            className="text-xs text-red-400/80 hover:text-red-300 mb-2"
          >
            删除本场
          </button>
        )}
      </div>

      <Field label="故事标题">
        <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <Field label="地点 / 时间 / 气氛">
        <div className="grid grid-cols-3 gap-1.5">
          <input className={inputCls} value={location} onChange={(e) => setLocation(e.target.value)} placeholder="地点" />
          <input className={inputCls} value={time} onChange={(e) => setTime(e.target.value)} placeholder="时间" />
          <input className={inputCls} value={mood} onChange={(e) => setMood(e.target.value)} placeholder="气氛" />
        </div>
      </Field>
      <Field label="背景">
        <input className={inputCls} value={background} onChange={(e) => setBackground(e.target.value)} />
      </Field>
      <Field label="开场">
        <input className={inputCls} value={opening} onChange={(e) => setOpening(e.target.value)} />
      </Field>

      <Field label={`对演角色（已选 ${characterIds.length}）`}>
        <div className="flex flex-wrap gap-1.5">
          {characters.map((c) => (
            <button
              key={c.character_id}
              type="button"
              onClick={() => toggleCharacter(c.character_id)}
              className={`text-xs px-2.5 py-1 rounded border ${
                characterIds.includes(c.character_id)
                  ? "border-emerald-500/70 bg-emerald-500/15 text-emerald-300"
                  : "border-slate-700 bg-slate-800/70 text-slate-300"
              }`}
            >
              {c.name}
            </button>
          ))}
        </div>
      </Field>

      <div className="grid grid-cols-2 gap-2">
        <Field label={`轮数：${maxRounds}`}>
          <input
            type="range" min={1} max={30} value={maxRounds}
            onChange={(e) => setMaxRounds(Number(e.target.value))} className="w-full"
          />
        </Field>
        <Field label="旁白">
          <button
            type="button"
            onClick={() => setNarrator((v) => !v)}
            className={`w-full px-2.5 py-1.5 rounded-lg text-xs border ${
              narrator
                ? "border-indigo-500/70 bg-indigo-500/15 text-indigo-300"
                : "border-slate-700 bg-slate-800 text-slate-400"
            }`}
          >
            {narrator ? "开启" : "关闭"}
          </button>
        </Field>
        {narrator && (
          <div className="col-span-2">
            <Field label="旁白模型（默认 = 跟随全局默认模型）">
              <EntityModelSelect value={narratorModel} onChange={setNarratorModel} />
            </Field>
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={create}
        disabled={busy || characterIds.length === 0}
        className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 disabled:opacity-40"
      >
        <Plus size={14} /> 开新场
      </button>

      {active && (
        <>
          <div className="grid grid-cols-3 gap-1.5 pt-1">
            {status === "waiting" || status === "ended" ? (
              <button
                type="button"
                onClick={() => act(() => startStory(active.session_id))}
                disabled={busy}
                className="col-span-3 inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-500 disabled:opacity-40"
              >
                <Play size={14} /> 开演
              </button>
            ) : status === "discussing" ? (
              <>
                <button
                  type="button"
                  onClick={() => act(() => pauseStory(active.session_id))}
                  className="inline-flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg bg-amber-600/80 text-white text-xs"
                >
                  <Pause size={12} /> 暂停
                </button>
                <button
                  type="button"
                  onClick={() => act(() => stopStory(active.session_id))}
                  className="inline-flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg bg-red-600/80 text-white text-xs"
                >
                  <Square size={12} /> 结束
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => act(() => resumeStory(active.session_id))}
                className="col-span-3 inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium"
              >
                <Play size={14} /> 继续
              </button>
            )}
          </div>

          <Field label="导演注入（旁白 / 突发事件 / 剧情指令）">
            <textarea
              className={`${inputCls} h-14`}
              value={injectText}
              onChange={(e) => setInjectText(e.target.value)}
              placeholder="如：窗外突然传来警笛声，两人的谈话被打断。"
            />
          </Field>
          <button
            type="button"
            onClick={async () => {
              if (!injectText.trim()) return;
              await injectStory(active.session_id, injectText);
              setInjectText("");
              onActive(await fetchStoryDetail(active.session_id));
            }}
            disabled={!injectText.trim() || status === "ended" || status === "waiting"}
            className="w-full px-3 py-1.5 rounded-lg bg-slate-800 text-slate-200 text-xs hover:bg-slate-700 disabled:opacity-40"
          >
            注入剧情
          </button>

          <div className="space-y-2 pt-1">
            <div className="text-xs text-slate-400">角色状态（手动掌控）</div>
            {active.characters.map((c) => (
              <div key={c.character_id} className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-2 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-200">{c.name}</span>
                  <span className="text-[10px] text-slate-400 font-mono">
                    本{c.current_ratio.id} / 自{c.current_ratio.ego} / 超{c.current_ratio.superego}
                  </span>
                </div>
                <div className="text-[10px] text-slate-400">
                  {Object.entries(c.emotion_state)
                    .filter(([, v]) => (v as number) > 0.05)
                    .map(([k, v]) => `${EMOTION_LABELS[k] ?? k} ${Math.round((v as number) * 100)}%`)
                    .join(" · ") || "平静"}
                </div>
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => act(() => setStoryEmotion(active.session_id, c.character_id, { anger: 0.8 }))}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-300 hover:bg-red-500/25"
                  >
                    愤怒↑
                  </button>
                  <button
                    type="button"
                    onClick={() => act(() => setStoryEmotion(active.session_id, c.character_id, { fear: 0.8 }))}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 hover:bg-amber-500/25"
                  >
                    恐惧↑
                  </button>
                  <button
                    type="button"
                    onClick={() => act(() => setStoryEmotion(active.session_id, c.character_id, undefined, undefined, true))}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 hover:bg-slate-600"
                  >
                    恢复自动
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}

function MessageCard({ msg }: { msg: StoryMessage }) {
  if (msg.entry_type === "narrator") {
    return (
      <div className="text-xs text-slate-400 italic leading-relaxed px-1">
        {msg.thinking || msg.speech}
      </div>
    );
  }
  if (msg.entry_type === "director") {
    return (
      <div className="text-xs text-amber-400/90 leading-relaxed px-1">
        <span className="font-semibold">[导演]</span> {msg.thinking || msg.speech}
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 p-2.5 space-y-1">
      <div className="text-xs font-semibold text-indigo-300">{msg.speaker_name}</div>
      {(msg.expression || msg.action) && (
        <div className="text-xs text-slate-400">
          {msg.expression && <span>（{msg.expression}）</span>} {msg.action}
        </div>
      )}
      {msg.speech && <div className="text-sm text-slate-100 leading-relaxed">「{msg.speech}」</div>}
      {msg.thinking && (
        <details className="pt-0.5">
          <summary className="text-[10px] text-slate-500 cursor-pointer">内心想法</summary>
          <div className="text-xs text-slate-500 italic mt-1">{msg.thinking}</div>
        </details>
      )}
    </div>
  );
}

function StagePanel({ active }: { active: StorySessionDetail | null }) {
  const [exportMd, setExportMd] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const tail = useMemo(() => {
    if (!active) return [];
    return active.transcript.slice(-40);
  }, [active]);

  const copy = async () => {
    if (!exportMd) return;
    await navigator.clipboard.writeText(exportMd);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  if (!active) {
    return (
      <Panel title="对演舞台">
        <div className="flex flex-col items-center justify-center py-16 text-slate-500">
          <Clapperboard size={40} className="mb-3 opacity-40" />
          <p className="text-sm">先在「人物库」捏人，再到「剧场控制台」开一场戏</p>
        </div>
      </Panel>
    );
  }

  return (
    <Panel
      title={`对演舞台 · ${active.title}`}
      actions={
        <button
          type="button"
          onClick={async () => {
            const res = await exportStory(active.session_id);
            setExportMd(res.markdown);
          }}
          className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700"
        >
          <Download size={12} /> 导出
        </button>
      }
    >
      <div className="text-xs text-slate-500">
        第 {active.current_round} / {active.max_rounds} 轮 · {active.transcript.length} 条
        {active.narrator_enabled ? " · 旁白开" : " · 旁白关"}
      </div>

      <div className="space-y-2">
        {tail.map((msg, i) => (
          <MessageCard key={i} msg={msg} />
        ))}
        {active.active_turn && (
          <div className="rounded-lg border border-indigo-500/40 bg-indigo-500/5 p-2.5">
            <div className="text-xs font-semibold text-indigo-300 mb-1">
              {active.active_turn.speaker_name} 正在演出…
            </div>
            <div className="text-xs text-slate-400 whitespace-pre-wrap font-mono">
              {active.active_turn.content}
              <span className="inline-block w-1.5 h-3 bg-indigo-400 align-middle animate-pulse ml-0.5" />
            </div>
          </div>
        )}
      </div>

      {exportMd && (
        <div className="rounded-lg border border-slate-700 bg-slate-950/80 p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-slate-400">导出预览</span>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={copy}
                className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300"
              >
                <Copy size={10} /> {copied ? "已复制" : "复制"}
              </button>
              <button
                type="button"
                onClick={() => setExportMd(null)}
                className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400"
              >
                关闭
              </button>
            </div>
          </div>
          <pre className="text-xs text-slate-300 whitespace-pre-wrap font-sans leading-relaxed max-h-72 overflow-y-auto">
            {exportMd}
          </pre>
        </div>
      )}
    </Panel>
  );
}

export default function StoryMachinePage() {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [sessions, setSessions] = useState<StorySessionSummary[]>([]);
  const [active, setActiveState] = useState<StorySessionDetail | null>(null);

  const STORAGE_KEY = "story_machine:active_session";

  // 记住当前场次：切窗口/刷新后回到页面自动恢复（演绎在后台持续进行）
  const setActive = useCallback((s: StorySessionDetail | null) => {
    setActiveState(s);
    if (s) {
      localStorage.setItem(STORAGE_KEY, s.session_id);
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      void fetchStoryDetail(saved)
        .then((d) => setActiveState(d))
        .catch(() => localStorage.removeItem(STORAGE_KEY));
    }
  }, []);

  // 从其他窗口/标签页切回来时立即刷新，避免后台节流导致的画面滞后
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        setActiveState((prev) => {
          if (prev) {
            void fetchStoryDetail(prev.session_id).then(setActiveState);
          }
          return prev;
        });
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  const refreshCharacters = useCallback(async () => {
    const res = await fetchCharacters();
    setCharacters(res.characters);
  }, []);

  const refreshSessions = useCallback(async () => {
    const res = await fetchStories();
    setSessions(res.sessions);
  }, []);

  useEffect(() => {
    void refreshCharacters();
    void refreshSessions();
  }, [refreshCharacters, refreshSessions]);

  useEffect(() => {
    if (active?.status !== "discussing") return;
    const timer = setInterval(async () => {
      try {
        setActive(await fetchStoryDetail(active.session_id));
      } catch {
        // 会话可能已删除，忽略
      }
    }, 1200);
    return () => clearInterval(timer);
  }, [active?.session_id, active?.status]);

  return (
    <div className="h-full flex gap-3 p-3 min-h-0">
      <div className="w-72 shrink-0 min-h-0">
        <CharacterLibraryPanel characters={characters} />
      </div>
      <div className="w-96 shrink-0 min-h-0">
        <TheaterPanel
          characters={characters}
          sessions={sessions}
          active={active}
          onActive={setActive}
          onSessionsChanged={refreshSessions}
        />
      </div>
      <div className="flex-1 min-h-0">
        <StagePanel active={active} />
      </div>
    </div>
  );
}
