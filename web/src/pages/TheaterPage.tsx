import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  Theater as TheaterIcon, Play, Square, Plus, X, MessageCircle, Send, Sparkles, ChevronDown, ChevronUp,
  Globe2, Swords, BookOpen, Box, Brain,
} from "lucide-react";
import { fetchCharacters, type Character } from "../lib/characterApi";
import {
  fetchTheaterWorlds, createTheaterWorld, createTheaterSession, preReadTheater,
  setTheaterBattleRatio, backstageChat, performRound, type World, type TheaterSession,
} from "../lib/theaterApi";

const STATS_DEFAULT = { 力量: 50, 敏捷: 50, 体质: 50, 智力: 50, 精神: 50 };

const TYPE_LABELS: Record<string, { label: string; cls: string }> = {
  fight: { label: "战斗型", cls: "bg-red-500/15 text-red-400" },
  plot: { label: "剧情型", cls: "bg-indigo-500/15 text-indigo-400" },
  talk: { label: "对话型", cls: "bg-emerald-500/15 text-emerald-400" },
};

// 角色颜色（按选角顺序分配，便于区分发言人）
const ROLE_COLORS = [
  { name: "#f87171", bg: "rgba(248,113,113,.12)", border: "rgba(248,113,113,.45)" },
  { name: "#60a5fa", bg: "rgba(96,165,250,.12)", border: "rgba(96,165,250,.45)" },
  { name: "#34d399", bg: "rgba(52,211,153,.12)", border: "rgba(52,211,153,.45)" },
  { name: "#fbbf24", bg: "rgba(251,191,36,.12)", border: "rgba(251,191,36,.45)" },
  { name: "#c084fc", bg: "rgba(192,132,252,.12)", border: "rgba(192,132,252,.45)" },
  { name: "#f472b6", bg: "rgba(244,114,182,.12)", border: "rgba(244,114,182,.45)" },
];

interface PerformMsg {
  kind: "narrator" | "turn" | "battle";
  narrator?: string;
  turn?: {
    character_id: string;
    name: string;
    thinking: string;
    expression: string;
    action: string;
    speech: string;
    emotion: { name: string; value: number } | Record<string, number>;
  };
  battleText?: string;
  meta?: string[];
  round: number;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-2.5">
      <label className="block text-xs text-slate-400 mb-1">{label}</label>
      {children}
    </div>
  );
}

const inputCls =
  "w-full bg-slate-800/80 border border-slate-700 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/60";

export default function TheaterPage() {
  const [mode, setMode] = useState<"discuss" | "perform">("perform");
  const [worlds, setWorlds] = useState<World[]>([]);
  const [selectedWorld, setSelectedWorld] = useState<World | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [pickedIds, setPickedIds] = useState<string[]>([]);
  const [title, setTitle] = useState("雨夜谈判");
  const [sceneType, setSceneType] = useState<"plot" | "battle" | "talk">("plot");
  const [location, setLocation] = useState("打烊的咖啡馆 / 深夜十一点 / 压抑潮湿");
  const [battleRatio, setBattleRatio] = useState(70);
  const [session, setSession] = useState<TheaterSession | null>(null);
  const [reading, setReading] = useState(false);
  const [readSteps, setReadSteps] = useState<TheaterSession["pre_read_steps"]>([]);
  const [consensus, setConsensus] = useState("");
  const [performMsgs, setPerformMsgs] = useState<PerformMsg[]>([]);
  const [performing, setPerforming] = useState(false);
  const [performRoundNum, setPerformRoundNum] = useState(0);
  const [maxRounds, setMaxRounds] = useState(6);
  const playingRef = useRef(false);
  const [directorText, setDirectorText] = useState("");
  const [worldview, setWorldview] = useState("两界分层；权柄总量守恒；禁开天位权柄。");
  const [newWorldName, setNewWorldName] = useState("");
  const [showNewWorld, setShowNewWorld] = useState(false);

  // 幕后聊天
  const [bsOpen, setBsOpen] = useState(true);
  const [bsMsgs, setBsMsgs] = useState<Array<{ role: "user" | "ai"; text: string }>>([
    { role: "ai", text: "我在幕后。想聊剧情走向、补世界观设定，或指挥下一幕演出都可以。" },
  ]);
  const [bsInput, setBsInput] = useState("");
  const [bsBusy, setBsBusy] = useState(false);
  const bsEndRef = useRef<HTMLDivElement>(null);

  const refreshWorlds = useCallback(async () => {
    try {
      const res = await fetchTheaterWorlds();
      setWorlds(res.worlds);
    } catch { /* ignore */ }
  }, []);

  const refreshCharacters = useCallback(async () => {
    try {
      const res = await fetchCharacters();
      setCharacters(res.characters || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    void refreshWorlds();
    void refreshCharacters();
  }, [refreshWorlds, refreshCharacters]);

  useEffect(() => {
    bsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [bsMsgs]);

  const createWorld = async () => {
    if (!newWorldName.trim()) return;
    try {
      const res = await createTheaterWorld({ name: newWorldName.trim(), worldview });
      setSelectedWorld(res.world);
      setNewWorldName("");
      setShowNewWorld(false);
      await refreshWorlds();
    } catch { /* ignore */ }
  };

  const startSession = async () => {
    if (!selectedWorld) return;
    try {
      const res = await createTheaterSession({
        world_id: selectedWorld.world_id,
        mode,
        title: title.trim() || "未命名演出",
        character_ids: pickedIds,
        scene: { location, scene_type: sceneType },
        battle_ratio: battleRatio,
      });
      setSession(res.session);
      setReadSteps([]);
      setConsensus("");
    } catch { /* ignore */ }
  };

  const doPreRead = async () => {
    if (!session) return;
    setReading(true);
    try {
      const res = await preReadTheater(session.session_id);
      setReadSteps(res.steps);
      setConsensus(res.consensus);
      setSession(res.session);
    } finally {
      setReading(false);
    }
  };

  const changeRatio = async (v: number) => {
    setBattleRatio(v);
    if (session) {
      try { await setTheaterBattleRatio(session.session_id, v); } catch { /* ignore */ }
    }
  };

  const doBackstage = async () => {
    const msg = bsInput.trim();
    if (!msg || !session || bsBusy) return;
    setBsMsgs((m) => [...m, { role: "user", text: msg }]);
    setBsInput("");
    setBsBusy(true);
    try {
      const res = await backstageChat(session.session_id, msg);
      setBsMsgs((m) => [...m, { role: "ai", text: res.reply }]);
    } catch {
      setBsMsgs((m) => [...m, { role: "ai", text: "（幕后 AI 暂时没接住，稍后再试）" }]);
    } finally {
      setBsBusy(false);
    }
  };

  const colorOf = (charId: string) => {
    const idx = pickedIds.indexOf(charId);
    return ROLE_COLORS[idx >= 0 ? idx % ROLE_COLORS.length : 0];
  };

  const playRound = async (director = "") => {
    if (!session || performing) return;
    setPerforming(true);
    try {
      const res = await performRound(session.session_id, director);
      setPerformRoundNum(res.round);
      setPerformMsgs((prev) => [
        ...prev,
        { kind: "narrator", narrator: res.narrator, round: res.round },
        ...res.turns.map((t) => ({ kind: "turn" as const, turn: t, round: res.round })),
      ]);
      // 战斗场景：追加打斗判定元数据（按比重）
      if (res.is_battle) {
        const first = res.turns[0];
        if (first) {
          const color = colorOf(first.character_id);
          setPerformMsgs((prev) => [
            ...prev,
            {
              kind: "battle",
              battleText: "",
              meta: [
                `文字演绎 ${res.battle_ratio}% · 数值判定 ${100 - res.battle_ratio}%`,
                `招式：${first.action || "蓄势"}（${first.name}）`,
                `判定参考：${color.name} 方力量 ${100 - res.battle_ratio > 50 ? "侧重" : "参考"}`,
              ],
              round: res.round,
            },
          ]);
        }
      }
      // 自动连播到目标轮次（未暂停时）
      if (playingRef.current && res.round < maxRounds) {
        setTimeout(() => void playRound(), 600);
      } else {
        playingRef.current = false;
      }
    } catch {
      setPerformMsgs((prev) => [...prev, { kind: "narrator", narrator: "（这一轮没有接住，稍后再试）", round: performRoundNum + 1 }]);
      playingRef.current = false;
    } finally {
      setPerforming(false);
    }
  };

  const startPlay = () => {
    if (!session) return;
    playingRef.current = true;
    void playRound();
  };

  const pauseScene = () => {
    playingRef.current = false;
  };

  const exportScene = () => {
    const lines = performMsgs.map((m) => {
      if (m.kind === "narrator") return `【旁白】${m.narrator}`;
      if (m.kind === "battle") return `【战斗】${(m.meta || []).join("；")}`;
      const t = m.turn!;
      return `${t.name}：${t.speech}${t.thinking ? `（思考：${t.thinking}）` : ""}${t.expression ? `（表情：${t.expression}）` : ""}${t.action ? `（动作：${t.action}）` : ""}`;
    });
    const blob = new Blob([lines.join("\n\n")], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "剧场演出记录.txt";
    a.click();
  };

  const handleDirector = async () => {
    const text = directorText.trim();
    if (!text || !session) return;
    setDirectorText("");
    await playRound(text);
  };

  const picked = characters.filter((c) => pickedIds.includes(c.character_id));

  return (
    <div className="h-[calc(100vh-3.5rem)] flex gap-3 p-3 min-h-0 bg-slate-950 overflow-hidden">
      {/* 左栏：控制台 */}
      <div className="w-72 shrink-0 rounded-xl border border-slate-700/60 bg-slate-900/60 flex flex-col min-h-0 overflow-auto">
        <div className="px-4 py-3 border-b border-slate-700/60 flex items-center gap-2">
          <TheaterIcon size={16} className="text-amber-400" />
          <h2 className="text-sm font-semibold text-slate-200">剧场</h2>
        </div>
        <div className="p-3 space-y-3">
          {/* 模式切换 */}
          <div className="flex rounded-lg bg-slate-800/80 border border-slate-700 p-1">
            <button
              type="button"
              onClick={() => setMode("discuss")}
              className={`flex-1 px-2 py-1.5 text-xs rounded-md transition-colors cursor-pointer ${mode === "discuss" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-slate-200"}`}
            >
              讨论模式
            </button>
            <button
              type="button"
              onClick={() => setMode("perform")}
              className={`flex-1 px-2 py-1.5 text-xs rounded-md transition-colors cursor-pointer ${mode === "perform" ? "bg-emerald-600 text-white" : "text-slate-400 hover:text-slate-200"}`}
            >
              演绎模式
            </button>
          </div>

          {/* 世界 */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-slate-400">当前世界</span>
              <button
                type="button"
                onClick={() => setShowNewWorld((v) => !v)}
                className="text-[11px] text-indigo-400 hover:text-indigo-300 cursor-pointer"
              >
                <Plus size={11} className="inline" /> 新建世界
              </button>
            </div>
            <select
              value={selectedWorld?.world_id || ""}
              onChange={(e) => setSelectedWorld(worlds.find((w) => w.world_id === e.target.value) || null)}
              className={inputCls}
            >
              <option value="">选择世界…</option>
              {worlds.map((w) => <option key={w.world_id} value={w.world_id}>{w.name}</option>)}
            </select>
            {showNewWorld && (
              <div className="mt-2 space-y-2">
                <input className={inputCls} placeholder="世界名称" value={newWorldName} onChange={(e) => setNewWorldName(e.target.value)} />
                <textarea className={`${inputCls} h-20 font-mono text-xs`} placeholder="世界观正文（规则/禁忌/力量体系）" value={worldview} onChange={(e) => setWorldview(e.target.value)} />
                <button type="button" onClick={createWorld} className="w-full px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-xs hover:bg-indigo-500 cursor-pointer">
                  创建世界
                </button>
              </div>
            )}
          </div>

          {/* 场景 */}
          <Field label="场景类型">
            <select className={inputCls} value={sceneType} onChange={(e) => setSceneType(e.target.value as typeof sceneType)}>
              <option value="plot">剧情对演</option>
              <option value="battle">战斗场景</option>
              <option value="talk">对话交锋</option>
            </select>
          </Field>
          <Field label="地点 / 时间 / 气氛">
            <input className={inputCls} value={location} onChange={(e) => setLocation(e.target.value)} />
          </Field>

          {/* 战斗比重 */}
          {sceneType === "battle" && (
            <div className="rounded-lg border border-red-500/25 bg-red-500/5 p-2.5">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[11px] text-red-300 flex items-center gap-1"><Swords size={11} /> 文字演绎 ↔ 数值判定</span>
                <span className="text-[11px] text-slate-300">
                  文字 <b>{battleRatio}%</b> · 数值 <b>{100 - battleRatio}%</b>
                </span>
              </div>
              <input type="range" min={0} max={100} value={battleRatio} onChange={(e) => changeRatio(Number(e.target.value))} className="w-full accent-indigo-500" />
              <p className="text-[10px] text-slate-500 mt-1">战斗中可随时调节：偏文字=自由描写，偏数值=属性判定</p>
            </div>
          )}

          {/* 选角 */}
          <div>
            <span className="text-xs text-slate-400 block mb-1">选角（人物库）</span>
            <div className="flex flex-wrap gap-1.5">
              {characters.map((c) => (
                <button
                  key={c.character_id}
                  type="button"
                  onClick={() => setPickedIds((prev) => prev.includes(c.character_id) ? prev.filter((x) => x !== c.character_id) : [...prev, c.character_id])}
                  className={`text-xs px-2.5 py-1 rounded-full border cursor-pointer ${pickedIds.includes(c.character_id) ? "bg-emerald-500/15 border-emerald-500/50 text-emerald-300" : "border-slate-700 bg-slate-800/70 text-slate-400"}`}
                >
                  {c.name}
                </button>
              ))}
              {characters.length === 0 && <span className="text-xs text-slate-600">人物库暂无角色</span>}
            </div>
          </div>

          <button type="button" onClick={startSession} className="w-full px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 cursor-pointer">
            <Plus size={14} className="inline mr-1" /> 创建剧场会话
          </button>

          {/* 控制：开演 / 暂停 / 注入 / 导出 */}
          <button
            type="button"
            onClick={startPlay}
            disabled={!session || performing}
            className="w-full px-3 py-2.5 mt-2 rounded-lg bg-emerald-600 text-white text-sm font-bold hover:bg-emerald-500 disabled:opacity-40 cursor-pointer"
          >
            <Play size={15} className="inline mr-1" /> {performing ? "演出中…（AI 生成中）" : "▶ 开演"}
          </button>
          <div className="grid grid-cols-3 gap-1.5 mt-2">
            <button
              type="button"
              onClick={pauseScene}
              disabled={!playingRef.current}
              className="px-2 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 hover:bg-slate-700 disabled:opacity-40 cursor-pointer"
            >
              暂停
            </button>
            <button
              type="button"
              onClick={() => void handleDirector()}
              disabled={!session}
              className="px-2 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-amber-300 hover:bg-slate-700 disabled:opacity-40 cursor-pointer"
            >
              注入
            </button>
            <button
              type="button"
              onClick={exportScene}
              disabled={performMsgs.length === 0}
              className="px-2 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 hover:bg-slate-700 disabled:opacity-40 cursor-pointer"
            >
              导出
            </button>
          </div>
          <div className="mt-2">
            <label className="text-[11px] text-slate-500 block mb-1">轮次：{performRoundNum} / {maxRounds}</label>
            <input
              type="range" min={1} max={10} value={maxRounds}
              onChange={(e) => setMaxRounds(Number(e.target.value))}
              className="w-full accent-indigo-500"
            />
          </div>
        </div>
      </div>

      {/* 中栏：演出区 */}
      <div className="flex-1 rounded-xl border border-slate-700/60 bg-slate-900/60 flex flex-col min-h-0 min-w-0">
        <div className="px-4 py-2.5 border-b border-slate-700/60 flex items-center gap-2">
          <span className={`text-[11px] px-2 py-0.5 rounded-full ${mode === "discuss" ? "bg-indigo-500/15 text-indigo-300" : "bg-emerald-500/15 text-emerald-300"}`}>
            {mode === "discuss" ? "讨论模式" : "演绎模式"}
          </span>
          {sceneType === "battle" && <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-500/15 text-red-300">战斗场景</span>}
          <span className="text-sm font-medium text-slate-200 truncate">{session?.title || title || "未开始"}</span>
          <span className="ml-auto text-[11px] text-slate-500">{selectedWorld ? `世界：${selectedWorld.name}` : "未选择世界"}</span>
        </div>

        <div className="flex-1 overflow-y-auto overflow-x-hidden p-4 space-y-3 min-w-0">
          {!session ? (
            <div className="h-full flex items-center justify-center text-slate-500 text-sm">
              选择世界与角色后「创建剧场会话」，然后「预读取」开演
            </div>
          ) : (
            <>
              {/* 预读取面板 */}
              <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-indigo-300 flex items-center gap-1">
                    <Sparkles size={12} /> 开演前 · AI 预读取
                  </span>
                  <button
                    type="button"
                    onClick={doPreRead}
                    disabled={reading}
                    className="px-3 py-1 rounded-lg bg-indigo-600 text-white text-xs hover:bg-indigo-500 disabled:opacity-40 cursor-pointer"
                  >
                    {reading ? "预读取中…" : session.pre_read_done ? "重新预读取" : "预读取后开演"}
                  </button>
                </div>
                {readSteps.length > 0 && (
                  <div className="grid grid-cols-2 gap-1.5">
                    {readSteps.map((s) => (
                      <div key={s.key} className={`text-[11px] px-2 py-1 rounded-md border ${s.status === "done" ? "border-emerald-500/30 text-emerald-300" : "border-red-500/30 text-red-300"}`}>
                        {s.status === "done" ? "✓" : "✗"} {s.label}{s.note ? `（${s.note}）` : ""}
                      </div>
                    ))}
                  </div>
                )}
                {consensus && (
                  <div className="mt-2 text-xs text-slate-300 bg-slate-800/70 border border-slate-700 rounded-lg p-2.5">
                    <span className="text-emerald-400 font-medium">共识摘要：</span>
                    {consensus}
                  </div>
                )}
              </div>

              {/* 演出消息流（仅中间滚动，左右栏固定） */}
              <div className="flex-1 space-y-3 min-w-0">
                {performMsgs.length === 0 && (
                  <div className="rounded-xl border border-dashed border-slate-700 flex flex-col items-center justify-center gap-3 text-slate-600 text-xs p-8">
                    {session.pre_read_done
                      ? (
                        <>
                          <span className="text-emerald-400">已预读取 ✓ 可以开始演出了</span>
                          <button
                            type="button"
                            onClick={startPlay}
                            disabled={performing}
                            className="px-6 py-3 rounded-xl bg-emerald-600 text-white text-sm font-bold hover:bg-emerald-500 disabled:opacity-40 cursor-pointer inline-flex items-center gap-2"
                          >
                            <Play size={16} /> {performing ? "演出中…（AI 生成中）" : "▶ 开始演出"}
                          </button>
                          <span className="text-slate-500">AI 实时生成：旁白 + 角色四通道（每轮约 15-30 秒）</span>
                        </>
                      )
                      : "完成预读取后开始演出"}
                  </div>
                )}
                {performMsgs.map((m, i) => {
                  if (m.kind === "narrator") {
                    return (
                      <div key={i} className="text-center text-slate-400 italic text-xs leading-relaxed max-w-[85%] mx-auto">
                        <div className="w-12 h-px bg-slate-700 mx-auto my-1.5" />
                        {m.narrator}
                        <div className="w-12 h-px bg-slate-700 mx-auto my-1.5" />
                      </div>
                    );
                  }
                  if (m.kind === "battle") {
                    return (
                      <div key={i} className="rounded-xl border border-red-500/35 bg-red-500/5 p-3">
                        <p className="text-[11px] text-red-300 font-medium mb-1">⚔️ 战斗判定</p>
                        <div className="flex flex-wrap gap-1.5">
                          {(m.meta || []).map((x, j) => (
                            <span key={j} className="text-[10px] border border-slate-700 px-2 py-0.5 rounded text-slate-400">
                              {x}
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  }
                  const t = m.turn!;
                  const color = colorOf(t.character_id);
                  const roleChar = characters.find((c) => c.character_id === t.character_id);
                  const roleSkills = roleChar?.skill_ids || [];
                  return (
                    <div key={i} className="max-w-[82%] break-words" style={{ borderLeft: `3px solid ${color.border}`, background: color.bg, borderRadius: 10, padding: "8px 12px" }}>
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <span className="text-sm font-semibold" style={{ color: color.name }}>{t.name}</span>
                        {roleSkills.length > 0 && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-300">Skills：{roleSkills.join("、")}</span>
                        )}
                      </div>
                      {/* 重要正文：台词 */}
                      {t.speech && <div className="text-sm text-slate-100 leading-relaxed break-words whitespace-pre-wrap">{t.speech}</div>}
                      {/* 辅助信息：用括号弱化 */}
                      <div className="text-[11px] text-slate-400 mt-1.5 leading-relaxed break-words">
                        {t.thinking && <span>（思考：{t.thinking}）</span>}
                        {t.expression && <span>（表情：{t.expression}）</span>}
                        {t.action && <span>（动作：{t.action}）</span>}
                        {t.emotion && typeof t.emotion === "object" && Object.keys(t.emotion).length > 0 && (
                          <span>（情绪：{("name" in t.emotion) ? String((t.emotion as { name: string }).name) : Object.keys(t.emotion).join("、")}）</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* 导演输入 */}
        <div className="px-4 py-2.5 border-t border-slate-700/60 flex gap-2">
          <input
            className="flex-1 bg-slate-800/80 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-amber-500/60"
            placeholder="导演指令：推进剧情 / 突发事件 / 指定角色行为…"
            disabled={!session}
            value={directorText}
            onChange={(e) => setDirectorText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) void handleDirector(); }}
          />
          <button type="button" onClick={() => void handleDirector()} disabled={!session || performing} className="px-4 py-2 rounded-lg bg-amber-600 text-white text-sm font-medium hover:bg-amber-500 disabled:opacity-40 cursor-pointer">
            发送指令
          </button>
        </div>
      </div>

      {/* 右栏：角色卡 */}
      <div className="w-80 shrink-0 rounded-xl border border-slate-700/60 bg-slate-900/60 flex flex-col min-h-0 overflow-auto">
        <div className="px-4 py-3 border-b border-slate-700/60">
          <h3 className="text-xs font-semibold text-slate-300 flex items-center gap-1.5"><BookOpen size={13} className="text-amber-400" /> 选中的角色</h3>
        </div>
        <div className="p-3 space-y-3">
          {picked.length === 0 && <p className="text-xs text-slate-600 text-center py-6">还没选角色</p>}
          {picked.map((c) => (
            <div key={c.character_id} className="rounded-xl border border-slate-700/60 bg-slate-800/50 p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-sm font-semibold text-slate-200">{c.name}</span>
                <div className="flex gap-1">
                  {(c.types || []).map((t) => (
                    <span key={t} className={`text-[10px] px-1.5 py-0.5 rounded ${TYPE_LABELS[t]?.cls || "bg-slate-600 text-slate-300"}`}>
                      {TYPE_LABELS[t]?.label || t}
                    </span>
                  ))}
                </div>
              </div>

              {/* 五维 */}
              <div className="mb-2">
                <p className="text-[10px] text-slate-500 mb-1">身体素质五维</p>
                {Object.entries(c.stats || STATS_DEFAULT).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2 mb-1">
                    <span className="w-8 text-[11px] text-slate-400">{k}</span>
                    <div className="flex-1 h-1.5 bg-slate-700/60 rounded-full overflow-hidden">
                      <div className="h-full bg-indigo-500 rounded-full" style={{ width: `${Math.min(100, Number(v))}%` }} />
                    </div>
                    <span className="w-7 text-right text-[11px] text-slate-300">{v}</span>
                  </div>
                ))}
              </div>

              {/* 情绪 */}
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-2 mb-2">
                <p className="text-[10px] text-amber-400 mb-1">情绪算法 · 三我</p>
                {Object.entries(c.current_ratio || c.base_ratio).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2 mb-0.5">
                    <span className="w-8 text-[10px] text-slate-500">{{ id: "本我", ego: "自我", superego: "超我" }[k] || k}</span>
                    <div className="flex-1 h-1 bg-slate-700/60 rounded-full overflow-hidden">
                      <div className="h-full bg-amber-500 rounded-full" style={{ width: `${Number(v)}%` }} />
                    </div>
                    <span className="w-8 text-right text-[10px] text-slate-400">{v}%</span>
                  </div>
                ))}
                <p className="text-[10px] text-slate-500 mt-1">情绪：{Object.keys(c.emotion_state || {}).join("、") || "平静"} · 压力 {c.pressure}</p>
              </div>

              {/* 能力 + 装备 */}
              <div className="flex flex-wrap gap-1 mb-2">
                {(c.abilities || []).map((a, i) => (
                  <span key={i} className="text-[10px] bg-slate-700/50 border border-slate-600 px-1.5 py-0.5 rounded text-slate-300">
                    {a.name} <b className="text-amber-400">Lv{a.level || 1}</b>
                  </span>
                ))}
                {(c.equipment || []).map((e, i) => (
                  <span key={`e${i}`} className="text-[10px] bg-indigo-500/10 border border-indigo-500/30 px-1.5 py-0.5 rounded text-indigo-300">
                    {e.name} {e.effect ? <b className="text-amber-400">{e.effect}</b> : null}
                  </span>
                ))}
              </div>

              {(c.skill_ids || []).length > 0 && (
                <p className="text-[10px] text-purple-300">Skills：{(c.skill_ids || []).join("、")}</p>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* 幕后聊天浮窗 */}
      <div className="fixed right-3 bottom-3 w-96 max-h-[60vh] flex flex-col rounded-2xl border border-purple-500/25 bg-slate-900 shadow-2xl shadow-slate-950/50 overflow-hidden z-40">
        <button
          type="button"
          onClick={() => setBsOpen((v) => !v)}
          className="flex items-center gap-2 px-3.5 py-2.5 bg-slate-800/90 border-b border-slate-700/60 cursor-pointer"
        >
          <MessageCircle size={15} className="text-purple-400" />
          <span className="text-xs font-medium text-slate-200">幕后 · 和 AI 聊</span>
          <span className="ml-auto text-[10px] text-slate-500">{bsOpen ? "收起" : "展开"}</span>
          {bsOpen ? <ChevronDown size={13} className="text-slate-500" /> : <ChevronUp size={13} className="text-slate-500" />}
        </button>
        {bsOpen && (
          <>
            <div className="flex-1 overflow-auto p-3 space-y-2 min-h-32">
              {bsMsgs.map((m, i) => (
                <div key={i} className={`max-w-[85%] ${m.role === "user" ? "ml-auto" : ""}`}>
                  <div className={`text-xs leading-relaxed px-3 py-2 rounded-xl border ${m.role === "user" ? "bg-indigo-600 border-indigo-600 text-white" : "bg-slate-800/80 border-slate-700 text-slate-300"}`}>
                    {m.text}
                  </div>
                </div>
              ))}
              <div ref={bsEndRef} />
            </div>
            <div className="flex gap-2 p-2.5 border-t border-slate-700/60">
              <input
                className="flex-1 bg-slate-800/80 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-purple-500/50"
                placeholder="讨论剧情 / 补设定 / 指挥演出…"
                value={bsInput}
                onChange={(e) => setBsInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) void doBackstage(); }}
                disabled={!session || bsBusy}
              />
              <button type="button" onClick={() => void doBackstage()} disabled={!session || bsBusy} className="px-3 py-1.5 rounded-lg bg-purple-600 text-white text-xs hover:bg-purple-500 disabled:opacity-40 cursor-pointer">
                <Send size={12} className="inline" />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
