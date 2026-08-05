import { useCallback, useEffect, useState, type ReactNode } from "react";
import { BookUser, Eraser, Plus, Save, Trash2 } from "lucide-react";
import {
  Character,
  StoryEvent,
  Trait,
  clearCharacterMemory,
  deleteCharacter,
  fetchCharacters,
  saveCharacter,
} from "@/lib/characterApi";

const inputCls =
  "w-full bg-slate-800/80 border border-slate-700 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/60";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-slate-400 mb-1 block">{label}</span>
      {children}
    </label>
  );
}

/** 三我占比：每个"我"都有独立数字输入框 + 滑杆，输入后自动归一化到 100 */
function RatioSliders({ value, onChange }: {
  value: { id: number; ego: number; superego: number };
  onChange: (v: { id: number; ego: number; superego: number }) => void;
}) {
  const update = (key: "id" | "ego" | "superego", raw: number) => {
    const clamped = Math.max(0, Math.min(100, Number.isFinite(raw) ? raw : 0));
    const next = { ...value };
    const others = (["id", "ego", "superego"] as const).filter((k) => k !== key);
    const rest = 100 - clamped;
    const totalOthers = value[others[0]] + value[others[1]] || 1;
    next[key] = clamped;
    next[others[0]] = Math.round((rest * value[others[0]]) / totalOthers);
    next[others[1]] = 100 - clamped - next[others[0]];
    onChange(next);
  };
  const rows: Array<{ key: "id" | "ego" | "superego"; label: string; color: string }> = [
    { key: "id", label: "本我", color: "accent-red-500" },
    { key: "ego", label: "自我", color: "accent-indigo-500" },
    { key: "superego", label: "超我", color: "accent-emerald-500" },
  ];
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.key} className="flex items-center gap-2">
          <span className="w-10 text-xs text-slate-400">{row.label}</span>
          <input
            type="number"
            min={0}
            max={100}
            value={Math.round(value[row.key])}
            onChange={(e) => update(row.key, Number(e.target.value))}
            className="w-16 px-2 py-1 rounded bg-slate-800 border border-slate-700 text-sm text-slate-200 font-mono focus:outline-none focus:border-indigo-500/60"
            aria-label={`${row.label}占比`}
          />
          <input
            type="range"
            min={0}
            max={100}
            value={Math.round(value[row.key])}
            onChange={(e) => update(row.key, Number(e.target.value))}
            className={`w-full ${row.color}`}
          />
          <span className="w-10 text-right text-xs text-slate-300 font-mono">
            {Math.round(value[row.key])}%
          </span>
        </div>
      ))}
    </div>
  );
}

const emptyCharacter = (): Character => ({
  character_id: "",
  name: "",
  base_ratio: { id: 33, ego: 34, superego: 33 },
  traits: [],
  events: [],
  hard_rules: [],
  soft_rules: [],
  temperature: 0.9,
  model_name: null,
  emotion_state: {},
  pinned_emotion: null,
  pinned_ratios: null,
  current_ratio: { id: 33, ego: 34, superego: 33 },
  pressure: 0,
  summary: "",
  memory_logs: [],
});

function parseTraitsText(text: string): Trait[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, id_delta = "0", ego_delta = "0", superego_delta = "0", amp = "1", regress = ""] = line.split(";");
      return {
        name: name.trim(),
        id_delta: Number(id_delta) || 0,
        ego_delta: Number(ego_delta) || 0,
        superego_delta: Number(superego_delta) || 0,
        emotion_amplifier: Number(amp) || 1,
        regress_rate: regress ? Number(regress) : null,
      };
    });
}

function parseEventsText(text: string): StoryEvent[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [title, description = "", triggers = "", shifts = "", rebase = ""] = line.split(";");
      const parsePairs = (s: string) => {
        const out: Record<string, number> = {};
        s.split(",").forEach((pair) => {
          const [k, v] = pair.split(":");
          if (k && v !== undefined) out[k.trim()] = Number(v) || 0;
        });
        return out;
      };
      return {
        title: title.trim(),
        description: description.trim(),
        triggers: triggers.split(",").map((t) => t.trim()).filter(Boolean),
        emotion_shift: parsePairs(shifts),
        ratio_rebase: parsePairs(rebase),
        decay: 0.02,
      };
    });
}

function serializeTraits(traits: Trait[]): string {
  return traits
    .map((t) =>
      [t.name, t.id_delta, t.ego_delta, t.superego_delta, t.emotion_amplifier, t.regress_rate ?? ""].join(";")
    )
    .join("\n");
}

function serializeEvents(events: StoryEvent[]): string {
  return events
    .map((ev) =>
      [
        ev.title,
        ev.description,
        ev.triggers.join(","),
        Object.entries(ev.emotion_shift).map(([k, v]) => `${k}:${v}`).join(","),
        Object.entries(ev.ratio_rebase).map(([k, v]) => `${k}:${v}`).join(","),
      ].join(";")
    )
    .join("\n");
}

export default function CharacterLibraryPage() {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [draft, setDraft] = useState<Character>(emptyCharacter());
  const [traitsText, setTraitsText] = useState("");
  const [eventsText, setEventsText] = useState("");
  const [hardRulesText, setHardRulesText] = useState("");
  const [softRulesText, setSoftRulesText] = useState("");
  const [saved, setSaved] = useState(false);

  const refresh = useCallback(async () => {
    const res = await fetchCharacters();
    setCharacters(res.characters);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const select = (c: Character) => {
    const copy = JSON.parse(JSON.stringify(c)) as Character;
    setDraft(copy);
    setTraitsText(serializeTraits(copy.traits));
    setEventsText(serializeEvents(copy.events));
    setHardRulesText(copy.hard_rules.join("\n"));
    setSoftRulesText(copy.soft_rules.join("\n"));
    setSaved(false);
  };

  const startNew = () => {
    setDraft(emptyCharacter());
    setTraitsText("");
    setEventsText("");
    setHardRulesText("");
    setSoftRulesText("");
    setSaved(false);
  };

  const save = async () => {
    if (!draft.name.trim()) return;
    await saveCharacter({
      character_id: draft.character_id,
      name: draft.name,
      base_ratio: draft.base_ratio,
      traits: parseTraitsText(traitsText),
      events: parseEventsText(eventsText),
      hard_rules: hardRulesText.split("\n").map((s) => s.trim()).filter(Boolean),
      soft_rules: softRulesText.split("\n").map((s) => s.trim()).filter(Boolean),
      temperature: draft.temperature,
      model_name: draft.model_name,
    });
    setSaved(true);
    await refresh();
  };

  return (
    <div className="h-full flex gap-3 p-3 min-h-0">
      {/* 左侧：人物列表 */}
      <div className="w-72 shrink-0 rounded-xl border border-slate-700/60 bg-slate-900/60 flex flex-col min-h-0">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/60">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <BookUser size={16} className="text-amber-400" /> 人物库
          </h2>
          <button
            type="button"
            onClick={startNew}
            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700"
          >
            <Plus size={12} /> 新角色
          </button>
        </div>
        <div className="p-3 overflow-y-auto space-y-2">
          {characters.map((c) => (
            <button
              key={c.character_id}
              type="button"
              onClick={() => select(c)}
              className={`w-full text-left px-3 py-2 rounded-lg border ${
                draft.character_id === c.character_id
                  ? "border-amber-500/70 bg-amber-500/10"
                  : "border-slate-700/70 bg-slate-800/50 hover:border-slate-600"
              }`}
            >
              <div className="text-sm font-medium text-slate-200">{c.name}</div>
              <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                本{c.base_ratio.id} / 自{c.base_ratio.ego} / 超{c.base_ratio.superego}
              </div>
              {c.memory_logs.length > 0 && (
                <div className="text-[10px] text-amber-500/70 mt-0.5">
                  记忆 {c.memory_logs.length} 条
                </div>
              )}
            </button>
          ))}
          {characters.length === 0 && (
            <div className="text-xs text-slate-500 text-center py-8">
              还没有角色，点右上角"新角色"创建
            </div>
          )}
        </div>
      </div>

      {/* 右侧：编辑表单 */}
      <div className="flex-1 rounded-xl border border-slate-700/60 bg-slate-900/60 flex flex-col min-h-0">
        <div className="px-4 py-3 border-b border-slate-700/60 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">
            {draft.character_id ? `编辑：${draft.name}` : "创建新角色"}
          </h2>
          {draft.character_id && (
            <button
              type="button"
              onClick={async () => {
                await deleteCharacter(draft.character_id);
                startNew();
                await refresh();
              }}
              className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-slate-800 text-red-400 hover:bg-red-500/10"
            >
              <Trash2 size={12} /> 删除
            </button>
          )}
        </div>
        <div className="p-4 overflow-y-auto space-y-3 max-w-3xl">
          <div className="grid grid-cols-2 gap-3">
            <Field label="名字">
              <input
                className={inputCls}
                value={draft.name}
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                placeholder="如：沈默"
              />
            </Field>
            <Field label={`随机性：${draft.temperature}`}>
              <input
                type="range" min={0.1} max={1.5} step={0.1}
                value={draft.temperature}
                onChange={(e) => setDraft((d) => ({ ...d, temperature: Number(e.target.value) }))}
                className="w-full mt-2"
              />
            </Field>
          </div>

          <Field label="性格底色（三我占比，各自输入或拖动，自动归一化到 100）">
            <RatioSliders
              value={draft.base_ratio}
              onChange={(base_ratio) => setDraft((d) => ({ ...d, base_ratio }))}
            />
          </Field>

          <Field label="性格特质（每行：名称;本我增量;自我增量;超我增量;情绪放大;回归率）">
            <textarea
              className={`${inputCls} font-mono text-xs h-20`}
              value={traitsText}
              onChange={(e) => setTraitsText(e.target.value)}
              placeholder={"毒舌;5;0;0;1.3;\n记仇;0;0;0;1;0.08"}
            />
          </Field>

          <Field label="重大事件（每行：标题;描述;触发词(逗号分隔);情绪偏移(如 anger:0.35,fear:0.2);占比重配(如 id:5,superego:8)）">
            <textarea
              className={`${inputCls} font-mono text-xs h-20`}
              value={eventsText}
              onChange={(e) => setEventsText(e.target.value)}
              placeholder={"被背叛;三年前合伙人卷款跑路;金钱,合作,信任;anger:0.35,fear:0.2;id:5,superego:8"}
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="硬规则（每行一条，绝对不可违反）">
              <textarea
                className={`${inputCls} font-mono text-xs h-16`}
                value={hardRulesText}
                onChange={(e) => setHardRulesText(e.target.value)}
                placeholder={"不许说脏话\n不许动手"}
              />
            </Field>
            <Field label="软规则（风格要求）">
              <textarea
                className={`${inputCls} font-mono text-xs h-16`}
                value={softRulesText}
                onChange={(e) => setSoftRulesText(e.target.value)}
                placeholder={"必须用中文\n说话简短"}
              />
            </Field>
          </div>

          <button
            type="button"
            onClick={save}
            className="inline-flex items-center justify-center gap-2 px-6 py-2.5 rounded-lg bg-amber-600 text-white text-sm font-medium hover:bg-amber-500"
          >
            <Save size={14} /> {saved ? "已保存" : "保存角色"}
          </button>

          {/* 人物日志：跨会话记忆 */}
          <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-slate-300">
                人物日志（跨会话记忆，共 {draft.memory_logs.length} 条）
              </span>
              {draft.memory_logs.length > 0 && (
                <button
                  type="button"
                  onClick={async () => {
                    if (!draft.character_id) return;
                    await clearCharacterMemory(draft.character_id);
                    await refresh();
                    const fresh = await fetchCharacters();
                    const updated = fresh.characters.find((c) => c.character_id === draft.character_id);
                    if (updated) select(updated);
                  }}
                  className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 hover:text-red-300"
                >
                  <Eraser size={10} /> 清空
                </button>
              )}
            </div>
            {draft.memory_logs.length === 0 ? (
              <div className="text-xs text-slate-500">
                暂无日志。角色在「故事机器」或「圆桌」中演出结束后，会自动生成经历日志，
                下次对演时他会记得这些事。
              </div>
            ) : (
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {[...draft.memory_logs].reverse().map((log, i) => (
                  <details key={i} className="text-xs">
                    <summary className="text-slate-300 cursor-pointer">
                      {log.title} · {(log.timestamp || "").slice(0, 10)} · {log.type}
                    </summary>
                    <div className="text-slate-400 mt-1 leading-relaxed pl-2 border-l border-slate-700">
                      {log.content}
                    </div>
                  </details>
                ))}
              </div>
            )}
          </div>

          <div className="text-xs text-slate-500 leading-relaxed">
            人物库的角色可在「故事机器」和「圆桌」中直接选用。
            <br />
            保存后角色的情绪/三我占比会在每次对演中持续演化。
          </div>
        </div>
      </div>
    </div>
  );
}

