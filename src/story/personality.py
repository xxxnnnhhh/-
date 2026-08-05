"""人格算法引擎 — 心理学启发的三我动态系统。

流水线（每轮角色发言）：
1. 事件触发检测（关键词命中 → 情绪偏移 + 人格重配）
2. 认知评价（底色滤镜：自我占比压制愤怒，本我占比放大冲动）
3. 三我动态浮动（基准 + 情绪扰动 → 归一化占比）
4. 行为层解锁（本我占比 → 温和/强烈/极端）
5. 思考深度（自我占比、冲突度、利害 → 浅/中/深）
6. 规则过滤（硬规则删除违规内容）
7. 状态更新（情绪衰减、占比回归、事件演变）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.story.models import Character, StoryEvent

logger = logging.getLogger("story.personality")

# Plutchik 八种基本情绪
EMOTION_KEYS = [
    "joy", "trust", "fear", "surprise",
    "sadness", "disgust", "anger", "anticipation",
]

EMOTION_LABELS = {
    "joy": "喜悦", "trust": "信任", "fear": "恐惧", "surprise": "惊讶",
    "sadness": "悲伤", "disgust": "厌恶", "anger": "愤怒", "anticipation": "期待",
}

# 每种情绪对 Δ 的默认系数（愤怒最强推本我，悲伤反而收着）
EMOTION_ID_COEFF = {
    "anger": 1.0, "disgust": 0.8, "fear": 0.4, "joy": 0.3,
    "surprise": 0.3, "anticipation": 0.2, "sadness": -0.5, "trust": -0.2,
}

# 情绪对超我的系数（恐惧/信任会激活约束与警惕）
EMOTION_SUPEREGO_COEFF = {
    "trust": 0.4, "fear": 0.2, "sadness": 0.2, "anger": 0.0,
}

DEFAULT_REGRESS_RATE = 0.30   # 每轮情绪回归基准的速度
MAX_ID_SHIFT = 30.0           # 本我占比单轮最大上浮（封顶，防止越界）

# 硬规则关键词检测（v1 精简版；完整规则过滤依赖提示词 + 修正重生成）
CURSE_WORDS = ["妈的", "操", "他妈的", "傻逼", "废物", "滚你妈", "去死", "混蛋", "王八蛋", "fuck", "shit"]
VIOLENCE_WORDS = ["打你", "揍你", "扇你", "掐死", "踢你", "砸死", "捅", "砍", "抽你"]
BEAT_WORDS = ["打", "揍", "扇", "掐", "踢", "砸", "捅", "砍"]


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
    """特质中的情绪放大系数（取最大，默认 1.0）。"""
    amp = 1.0
    for t in character.traits:
        if t.emotion_amplifier > 1.0:
            amp = max(amp, t.emotion_amplifier)
    return amp


def regress_rate(character: Character) -> float:
    """回归率：特质可覆盖（记仇 = 慢回归）。"""
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
    """认知评价（Lazarus）：底色滤镜修改原始情绪。

    - 自我占比高 → 愤怒/厌恶等攻击性情绪被理性压制
    - 本我占比高 → 冲动放大
    - 手动钉住的情绪直接返回
    """
    if character.pinned_emotion:
        return dict(character.pinned_emotion)

    base = effective_base(character)
    ego = base["ego"] / 100.0
    idr = base["id"] / 100.0
    amp = emotion_amplifier(character)

    result = {}
    for key in EMOTION_KEYS:
        val = float(emotion.get(key, 0.0))
        val = clamp(val)
        if key in ("anger", "disgust"):
            val = val * (1.0 - 0.35 * ego) * amp      # 自我压制攻击性
        elif key in ("fear", "sadness"):
            val = val * (1.0 - 0.25 * ego)            # 自我安抚恐惧悲伤
        elif key in ("joy", "surprise", "anticipation"):
            val = val * (1.0 + 0.25 * idr) * amp      # 本我放大冲动类情绪
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
    # 防止负值
    for k in raw:
        raw[k] = max(0.0, raw[k])
    return normalize_ratios(raw)


def behavior_layer(id_ratio: float) -> str:
    """行为层：本我占比决定可及的动作层级。"""
    if id_ratio >= 70:
        return "极端"
    if id_ratio >= 50:
        return "强烈"
    return "温和"


def thinking_depth(ratios: dict, conflict: float | None = None, stakes: float = 0.5) -> str:
    """思考深度：自我占比 + 本我/超我冲突 + 利害。"""
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
    """事件重配基准：长期影响底色，随激活次数衰减。"""
    base = dict(character.base_ratio)
    for event in events:
        intensity = max(0.0, 1.0 - event.decay * event.active_count)
        for key, val in (event.ratio_rebase or {}).items():
            if key in ("id", "ego", "superego"):
                base[key] = float(base.get(key, 0)) + float(val) * intensity
        event.active_count += 1
    character.base_ratio = normalize_ratios(base)


def update_state(character: Character, emotion: dict, activated_events: list[StoryEvent]) -> None:
    """状态更新：情绪衰减 + 占比回归 + 事件演变。"""
    # 情绪惯性：旧情绪衰减，新情绪并入
    rate = regress_rate(character)
    old = character.emotion_state
    merged = {}
    for key in EMOTION_KEYS:
        prev = float(old.get(key, 0.0))
        new = float(emotion.get(key, 0.0))
        merged[key] = clamp(prev * (1.0 - rate) + new * 0.7)
    character.emotion_state = merged

    # 占比向基准回归
    base = effective_base(character)
    current = character.current_ratio or dict(character.base_ratio)
    character.current_ratio = normalize_ratios({
        "id": current.get("id", 0) + (base["id"] - current.get("id", 0)) * rate,
        "ego": current.get("ego", 0) + (base["ego"] - current.get("ego", 0)) * rate,
        "superego": current.get("superego", 0) + (base["superego"] - current.get("superego", 0)) * rate,
    })

    # 事件重配（先更新再回归，保证基准已含事件影响）
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
    """检查硬规则。返回违规说明列表（空 = 合规）。"""
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
    """硬过滤：删除明显的违规词。"""
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
            # 动作通道出现针对人的暴力词 → 降级为克制动作
            action = str(result.get("action", ""))
            if any(w in action for w in VIOLENCE_WORDS):
                result["action"] = "（攥紧的拳头缓缓松开，深吸一口气，把动作压了下去）"
    return result
