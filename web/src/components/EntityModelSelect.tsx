import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Loader2 } from "lucide-react";
import { getModelProviders } from "../lib/api";
import type { ModelProvider } from "../types";

interface Props {
  /** 当前模型，格式 "provider_id:model_name"，null 表示使用默认模型 */
  value: string | null;
  onChange: (modelId: string | null) => void;
  disabled?: boolean;
  compact?: boolean;
}

export default function EntityModelSelect({
  value,
  onChange,
  disabled = false,
  compact = false,
}: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [providers, setProviders] = useState<Record<string, Omit<ModelProvider, "id">>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getModelProviders()
      .then((res) => setProviders(res.providers))
      .catch(() => setProviders({}))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const [providerId, modelName] = (value || "").split(":", 2);
  const provider = providerId ? providers[providerId] : null;
  const label = value
    ? `${provider?.name || providerId} - ${modelName}`
    : "默认模型";

  const models: { providerId: string; modelName: string; label: string }[] = [];
  for (const [pid, p] of Object.entries(providers)) {
    for (const m of p.models || []) {
      models.push({ providerId: pid, modelName: m, label: `${p.name} - ${m}` });
    }
  }

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        title="切换模型（影响本角色/席位的所有生成）"
        className={`inline-flex items-center gap-1.5 rounded-md border border-border/40 bg-slate-700/60 text-slate-300 hover:text-indigo-300 transition-colors disabled:opacity-40 ${
          compact ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-xs"
        }`}
      >
        {loading ? (
          <Loader2 size={12} className="animate-spin" aria-hidden="true" />
        ) : (
          <ChevronDown size={12} aria-hidden="true" />
        )}
        <span className="max-w-40 truncate">{loading ? "加载模型…" : label}</span>
      </button>

      {open && (
        <div className="absolute right-0 z-40 mt-1 w-64 overflow-hidden rounded-xl border border-slate-600/80 bg-slate-800 p-1.5 shadow-2xl shadow-slate-950/50">
          <div className="max-h-72 overflow-y-auto">
            <button
              type="button"
              onClick={() => {
                onChange(null);
                setOpen(false);
              }}
              className={`flex min-h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left text-sm transition-colors ${
                !value
                  ? "bg-indigo-500/15 text-indigo-100"
                  : "text-slate-300 hover:bg-slate-700/70 hover:text-slate-100"
              }`}
            >
              <span className="min-w-0 flex-1 truncate">默认模型</span>
              {!value ? <Check size={14} className="shrink-0 text-indigo-400" /> : null}
            </button>
            {models.length === 0 && !loading && (
              <p className="p-2.5 text-sm text-slate-500">
                暂无可用模型，请先在「配置 → 模型设置」中添加
              </p>
            )}
            {models.map((m) => {
              const active = m.providerId === providerId && m.modelName === modelName;
              return (
                <button
                  key={`${m.providerId}:${m.modelName}`}
                  type="button"
                  onClick={() => {
                    onChange(`${m.providerId}:${m.modelName}`);
                    setOpen(false);
                  }}
                  className={`flex min-h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left text-sm transition-colors ${
                    active
                      ? "bg-indigo-500/15 text-indigo-100"
                      : "text-slate-300 hover:bg-slate-700/70 hover:text-slate-100"
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate">{m.label}</span>
                  {active ? <Check size={14} className="shrink-0 text-indigo-400" /> : null}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
