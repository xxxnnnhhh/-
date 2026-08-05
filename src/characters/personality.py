"""人格算法引擎 — 心理学启发的三我动态系统（人物库共享）。

流水线（每轮角色发言）：
1. 事件触发检测 → 2. 认知评价（底色滤镜）→ 3. 三我动态浮动
4. 行为层解锁 → 5. 思考深度 → 6. 规则过滤 → 7. 状态更新
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from src.characters.models import Character, StoryEvent

logger = logging.getLogger("characters.personality")

# Plutchik 八种基本情绪
EMOTION_KEYS = [
    "joy", "trust", "fear", "surprise",
    "sadness", "disgust", "anger", "anticipation",
]

EMOTION_LABELS = {
    "joy": "喜悦", "trust": "信任", "fear": "恐惧", "surprise": "惊讶",
    "sadness": "悲伤", "disgust": "厌恶", "anger": "愤怒", "anticipation": "期待",
}

# 每种情绪对 Δ 的默认系数
EMOTION_ID_COEFF = {
    "anger": 1.0, "disgust": 0.8, "fear": 0.4, "joy": 0.3,
    "surprise": 0.3, "anticipation": 0.2, "sadness": -0.5, "trust": -0.2,
}

EMOTION_SUPEREGO_COEFF = {
    "trust": 0.4, "fear": 0.2, "sadness": 0.2, "anger": 0.0,
}

DEFAULT_REGRESS_RATE = 0.30
MAX_ID_SHIFT = 30.0

CURSE_WORDS = [
    "他妈的", "他妈", "妈的", "你妈", "妈的逼", "草泥马", "卧槽", "我操", "操",
    "傻逼", "傻b", "沙比", "废物", "滚你妈", "去死", "混蛋", "王八蛋", "畜生",
    "fuck", "shit", "bitch",
]
VIOLENCE_WORDS = ["打你", "揍你", "扇你", "掐死", "踢你", "砸死", "捅", "砍", "抽你"]


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def normalize_ratios(ratio: dict) -> dict:
    """归一化三我占比，保证和为 100。"""
    total = max(
        1e-6,
        float(ratio.get("id", 0)) + float(ratio.get("ego", 0)) + float(ratio.get("superego", 0)),
    )
    return {
        "id": round(100.0 * float(ratio.get("id", 0)) / total, 1),
        "ego": round(100.0 * float(ratio.get("ego", 0)) / total, 1),
        "superego": round(100.0 * float(ratio.get("superego", 0)) / total, 1),
    }


def effective_base(character: Character) -> dict:
    """基准占比 + 特质增量 → 有效底色。"""
    base = dict(character.base_ratio)
    base["id"] = float(base.get("id", 33)) + sum(t.id_delta for t in character.traits)
    base["ego"] = float(base.get("ego", 34)) + sum(t.ego_delta for t in character.traits)
    base["superego"] = float(base.get("superego", 33)) + sum(t.superego_delta for t in character.traits)
    return normalize_ratios(base)


def emotion_amplifier(character: Character) -> float:
    amp = 1.0
    for t in character.traits:
        if t.emotion_amplifier > 1.0:
            amp = max(amp, t.emotion_amplifier)
    return amp


def regress_rate(character: Character) -> float:
    for t in character.traits:
        if t.regress_rate is not None:
            return clamp(t.regress_rate, 0.01, 0.9)
    return DEFAULT_REGRESS_RATE


def trigger_events(character: Character, context_text: str) -> tuple[list[StoryEvent], dict]:
    """关键词命中事件触发。返回 (命中的事件, 聚合情绪偏移)。"""
    hits: list[StoryEvent] = []
    total_shift: dict = {}
    lowered = (context_text or "").lower()
    for event in character.events:
        if not event.triggers:
            continue
        matched = any(k.lower() in lowered for k in event.triggers if k)
        if matched:
            hits.append(event)
            intensity = max(0.0, 1.0 - event.decay * event.active_count)
            for key, val in (event.emotion_shift or {}).items():
                total_shift[key] = total_shift.get(key, 0.0) + float(val) * intensity
    return hits, total_shift


def appraise_emotion(character: Character, emotion: dict) -> dict:
    """认知评价（Lazarus）：底色滤镜修改原始情绪。"""
    if character.pinned_emotion:
        return dict(character.pinned_emotion)

    base = effective_base(character)
    ego = base["ego"] / 100.0
    idr = base["id"] / 100.0
    amp = emotion_amplifier(character)

    result = {}
    for key in EMOTION_KEYS:
        val = clamp(float(emotion.get(key, 0.0)))
        if key in ("anger", "disgust"):
            val = val * (1.0 - 0.35 * ego) * amp
        elif key in ("fear", "sadness"):
            val = val * (1.0 - 0.25 * ego)
        elif key in ("joy", "surprise", "anticipation"):
            val = val * (1.0 + 0.25 * idr) * amp
        result[key] = clamp(val)
    return result


def compute_ratios(character: Character, emotion: dict) -> dict:
    """三我动态浮动：基准 + 情绪扰动 → 归一化当前占比。"""
    if character.pinned_ratios:
        return normalize_ratios(character.pinned_ratios)

    base = effective_base(character)
    amp = emotion_amplifier(character)

    id_shift = sum(EMOTION_ID_COEFF.get(k, 0.0) * float(emotion.get(k, 0.0)) for k in EMOTION_KEYS)
    id_shift = clamp(id_shift * amp * 30.0, -15.0, MAX_ID_SHIFT)

    superego_shift = sum(
        EMOTION_SUPEREGO_COEFF.get(k, 0.0) * float(emotion.get(k, 0.0)) for k in EMOTION_KEYS
    )
    superego_shift = clamp(superego_shift * 15.0, -10.0, 15.0)

    raw = {
        "id": base["id"] + id_shift,
        "ego": base["ego"] - id_shift * 0.6,
        "superego": base["superego"] + superego_shift,
    }
    for k in raw:
        raw[k] = max(0.0, raw[k])
    return normalize_ratios(raw)


def behavior_layer(id_ratio: float) -> str:
    if id_ratio >= 70:
        return "极端"
    if id_ratio >= 50:
        return "强烈"
    return "温和"


def thinking_depth(ratios: dict, conflict: float | None = None, stakes: float = 0.5) -> str:
    ego = ratios.get("ego", 50) / 100.0
    if conflict is None:
        conflict = abs(ratios.get("id", 30) - ratios.get("superego", 30)) / 100.0
    score = 0.25 * ego + 0.35 * conflict + 0.40 * clamp(stakes)
    if score >= 0.55:
        return "深"
    if score >= 0.30:
        return "中"
    return "浅"


def apply_event_rebase(character: Character, events: list[StoryEvent]) -> None:
    base = dict(character.base_ratio)
    for event in events:
        intensity = max(0.0, 1.0 - event.decay * event.active_count)
        for key, val in (event.ratio_rebase or {}).items():
            if key in ("id", "ego", "superego"):
                base[key] = float(base.get(key, 0)) + float(val) * intensity
        event.active_count += 1
    character.base_ratio = normalize_ratios(base)


def update_state(character: Character, emotion: dict, activated_events: list[StoryEvent]) -> None:
    rate = regress_rate(character)
    old = character.emotion_state
    merged = {}
    for key in EMOTION_KEYS:
        prev = float(old.get(key, 0.0))
        new = float(emotion.get(key, 0.0))
        merged[key] = clamp(prev * (1.0 - rate) + new * 0.7)
    character.emotion_state = merged

    base = effective_base(character)
    current = character.current_ratio or dict(character.base_ratio)
    character.current_ratio = normalize_ratios({
        "id": current.get("id", 0) + (base["id"] - current.get("id", 0)) * rate,
        "ego": current.get("ego", 0) + (base["ego"] - current.get("ego", 0)) * rate,
        "superego": current.get("superego", 0) + (base["superego"] - current.get("superego", 0)) * rate,
    })

    if activated_events:
        apply_event_rebase(character, activated_events)

    character.updated_at = datetime.now(timezone.utc).isoformat()


# ============================================================
# 规则过滤
# ============================================================

def _rule_hits(text: str, rule: str) -> list[str]:
    hits: list[str] = []
    lowered = (text or "").lower()
    if "脏话" in rule or "骂人" in rule:
        hits.extend(w for w in CURSE_WORDS if w in lowered)
    if "动手" in rule or "暴力" in rule:
        hits.extend(w for w in VIOLENCE_WORDS if w in lowered)
    return hits


def check_rules(character: Character, channels: dict) -> list[str]:
    violations: list[str] = []
    text = " ".join(
        str(channels.get(k, "")) for k in ("expression", "action", "speech")
    )
    for rule in character.hard_rules:
        hits = _rule_hits(text, rule)
        if hits:
            violations.append(f"违反规则「{rule}」：命中 {', '.join(hits[:5])}")
    return violations


def mask_violations(channels: dict, character: Character) -> dict:
    result = dict(channels)
    for rule in character.hard_rules:
        if "脏话" in rule or "骂人" in rule:
            for key in ("expression", "action", "speech"):
                lowered = str(result.get(key, ""))
                for w in CURSE_WORDS:
                    if w in lowered:
                        result[key] = lowered.replace(w, "***")
                        lowered = result[key]
        if "动手" in rule or "暴力" in rule:
            action = str(result.get("action", ""))
            if any(w in action for w in VIOLENCE_WORDS):
                result["action"] = "（攥紧的拳头缓缓松开，深吸一口气，把动作压了下去）"
    return result


# ============================================================
# 四通道解析（故事机器与圆桌共用）
# ============================================================

_SECTION_RE = re.compile(r"【(?P<key>情绪|内心|表情|动作|台词)】(?P<value>.*?)(?=【|$)", re.S)


def _parse_emotion(text: str) -> dict:
    result = {}
    tokens = re.split(r"[、，,;\s]+", text.strip())
    label_to_key = {v: k for k, v in EMOTION_LABELS.items()}
    for token in tokens:
        if ":" not in token:
            continue
        label, _, raw = token.partition(":")
        label = label.strip().lower()
        key = label_to_key.get(label, label)
        if key not in EMOTION_KEYS:
            continue
        try:
            result[key] = clamp(float(raw.strip()))
        except ValueError:
            continue
    return result


def parse_turn(text: str) -> dict:
    """解析四通道表演。优先 JSON，其次【标记】格式。"""
    result = {
        "thinking": "", "expression": "", "action": "", "speech": "",
        "emotion": {},
    }
    if not text:
        return result

    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                for key in ("thinking", "expression", "action", "speech"):
                    result[key] = str(data.get(key, "") or "")
                emo = data.get("emotion")
                if isinstance(emo, dict):
                    result["emotion"] = _parse_emotion(
                        "、".join(f"{k}:{v}" for k, v in emo.items())
                    )
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    for match in _SECTION_RE.finditer(stripped):
        key = match.group("key")
        value = match.group("value").strip()
        if key == "情绪":
            result["emotion"] = _parse_emotion(value)
        elif key == "内心":
            result["thinking"] = value
        elif key == "表情":
            result["expression"] = value.strip("（）()")
        elif key == "动作":
            result["action"] = value.strip("（）()")
        elif key == "台词":
            result["speech"] = value.strip("「」\"'")

    if not any((result["thinking"], result["expression"], result["action"], result["speech"])):
        result["speech"] = stripped
    return result


def format_character_content(channels: dict) -> str:
    """把四通道渲染为发言内容（圆桌等场景使用）。"""
    lines = []
    if channels.get("thinking"):
        lines.append(f"（内心：{channels['thinking']}）")
    if channels.get("expression"):
        lines.append(f"（{channels['expression']}）")
    if channels.get("action"):
        lines.append(channels["action"])
    if channels.get("speech"):
        lines.append(f"「{channels['speech']}」")
    return "\n".join(lines) if lines else str(channels.get("speech", ""))
