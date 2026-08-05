"""人格引擎 — 由共享人物库模块提供（故事机器复用）。"""
from src.characters.personality import (
    DEFAULT_REGRESS_RATE,
    EMOTION_ID_COEFF,
    EMOTION_KEYS,
    EMOTION_LABELS,
    EMOTION_SUPEREGO_COEFF,
    MAX_ID_SHIFT,
    appraise_emotion,
    apply_event_rebase,
    behavior_layer,
    check_rules,
    clamp,
    compute_ratios,
    effective_base,
    emotion_amplifier,
    format_character_content,
    mask_violations,
    normalize_ratios,
    parse_turn,
    regress_rate,
    thinking_depth,
    trigger_events,
    update_state,
)

__all__ = [
    "DEFAULT_REGRESS_RATE", "EMOTION_ID_COEFF", "EMOTION_KEYS", "EMOTION_LABELS",
    "EMOTION_SUPEREGO_COEFF", "MAX_ID_SHIFT", "appraise_emotion", "apply_event_rebase",
    "behavior_layer", "check_rules", "clamp", "compute_ratios", "effective_base",
    "emotion_amplifier", "format_character_content", "mask_violations",
    "normalize_ratios", "parse_turn", "regress_rate", "thinking_depth",
    "trigger_events", "update_state",
]

