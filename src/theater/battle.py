"""战斗判定：文字演绎 ↔ 数值判定（比重可调）。

数值判定综合：五维基础值 + 能力加值 + 装备加值 + 情绪修正。
比重 ratio 表示"文字演绎"占比（0-100）：
- ratio 高（偏文字）：判定作为弱参考，AI 自由描写战斗。
- ratio 低（偏数值）：判定严格，结果明确影响剧情。
"""

from __future__ import annotations

import random
from typing import Any


DEFAULT_STATS = {"力量": 50, "敏捷": 50, "体质": 50, "智力": 50, "精神": 50}

# 情绪修正表：情绪 → {属性: 修正值}
EMOTION_MODIFIERS: dict[str, dict[str, int]] = {
    "愤怒": {"力量": 5, "智力": -3, "精神": -2},
    "恐惧": {"敏捷": 3, "力量": -4, "精神": -3},
    "悲伤": {"力量": -3, "智力": 2},
    "兴奋": {"敏捷": 4, "力量": 2, "智力": -2},
    "冷静": {"智力": 4, "精神": 3},
    "坚定": {"力量": 3, "精神": 4},
}


def _emotion_name(emotion_state: dict[str, Any]) -> str:
    """从情绪状态中取出强度最高的情绪名（中文）。"""
    if not emotion_state:
        return ""
    # 兼容 "anger": 0.62 这类英文键 → 映射中文
    key_to_cn = {
        "anger": "愤怒", "fear": "恐惧", "sadness": "悲伤", "joy": "兴奋",
        "calm": "冷静", "determination": "坚定", "disgust": "厌恶", "surprise": "惊讶",
    }
    best = ""
    best_val = 0.0
    for k, v in emotion_state.items():
        try:
            val = float(v)
        except (TypeError, ValueError):
            continue
        if val > best_val:
            best_val = val
            best = key_to_cn.get(str(k).lower(), str(k))
    return best


def _parse_bonus(effect: str) -> int:
    """解析装备效果中的数值加成，如 '力量+5' → 5、'敏捷+2' → 2。"""
    import re

    m = re.search(r"([+-]?\d+)", effect or "")
    return int(m.group(1)) if m else 0


def _ability_bonus(abilities: list[dict], stat_name: str) -> int:
    """能力加值：与属性同名或关键词匹配时提供加值。"""
    total = 0
    for ab in abilities or []:
        name = str(ab.get("name", ""))
        level = int(ab.get("level", 1) or 1)
        if stat_name in name or name in stat_name:
            total += level
    return total


def compute_effective_stat(
    stats: dict[str, int],
    *,
    abilities: list[dict] | None = None,
    equipment: list[dict] | None = None,
    emotion_state: dict[str, Any] | None = None,
) -> dict[str, int]:
    """计算有效属性：基础五维 + 能力 + 装备 + 情绪修正。"""
    base = {k: int(v) for k, v in (stats or DEFAULT_STATS).items()}
    result = dict(base)
    detail: dict[str, list[str]] = {}

    for ab in abilities or []:
        name = str(ab.get("name", ""))
        level = int(ab.get("level", 1) or 1)
        for stat in result:
            if stat in name or name in stat:
                result[stat] += level
                detail.setdefault(stat, []).append(f"能力[{name}]+{level}")

    for eq in equipment or []:
        effect = str(eq.get("effect", "") or "")
        bonus = _parse_bonus(effect)
        if bonus:
            # 装备效果格式如 "力量+5"，取属性名
            import re

            m = re.match(r"([\u4e00-\u9fa5]+)\s*[+-]", effect)
            if m and m.group(1) in result:
                result[m.group(1)] += bonus
                detail.setdefault(m.group(1), []).append(f"装备[{eq.get('name', '')}]{bonus:+d}")

    emo = _emotion_name(emotion_state or {})
    if emo and emo in EMOTION_MODIFIERS:
        for stat, mod in EMOTION_MODIFIERS[emo].items():
            if stat in result:
                result[stat] += mod
                detail.setdefault(stat, []).append(f"情绪[{emo}]{mod:+d}")

    return result


def resolve(
    *,
    attacker_stats: dict[str, int],
    defender_stats: dict[str, int] | None = None,
    abilities: list[dict] | None = None,
    equipment: list[dict] | None = None,
    emotion_state: dict[str, Any] | None = None,
    attack_stat: str = "力量",
    defense_stat: str = "敏捷",
    ratio: int = 70,
    difficulty: int = 0,
    seed: int | None = None,
) -> dict[str, Any]:
    """判定一次战斗行为。

    Args:
        ratio: 文字演绎占比（0-100）。越高判定越宽松（数值影响弱），越低判定越严格。
        difficulty: 难度修正（正数更难）。

    Returns:
        {success, roll, threshold, bonuses, effective_attack, effective_defense,
         emotion, detail, ratio, guidance}
    """
    rng = random.Random(seed)
    eff_attack = compute_effective_stat(
        attacker_stats, abilities=abilities, equipment=equipment, emotion_state=emotion_state
    )
    attack_val = eff_attack.get(attack_stat, 50)

    eff_defense = compute_effective_stat(defender_stats or {}, emotion_state=emotion_state)
    defense_val = eff_defense.get(defense_stat, 50)

    # 比重调节：ratio 越高（偏文字），判定阈值越宽松（数值只作参考）
    slack = (100 - ratio) / 100.0  # 0（纯文字）~ 1（纯数值）
    threshold = max(1, attack_val - defense_val + difficulty + int(slack * 40))
    roll = rng.randint(1, 100)
    success = roll >= threshold

    # 情绪名称（中文）与修正明细
    emotion = _emotion_name(emotion_state or {})
    bonuses: dict[str, list[str]] = {}
    for stat, detail_list in compute_bonus_details(
        abilities, equipment, emotion_state, attack_stat
    ).items():
        bonuses[stat] = detail_list

    if ratio >= 80:
        guidance = "偏文字演绎：以描写为主，判定仅作参考。"
    elif ratio <= 30:
        guidance = "偏数值判定：结果明确影响剧情走向。"
    else:
        guidance = "文字与数值平衡：描写与判定结合。"

    return {
        "success": success,
        "roll": roll,
        "threshold": threshold,
        "attack_stat": attack_stat,
        "defense_stat": defense_stat,
        "effective_attack": attack_val,
        "effective_defense": defense_val,
        "emotion": emotion,
        "bonuses": bonuses,
        "ratio": ratio,
        "guidance": guidance,
    }


def compute_bonus_details(
    abilities: list[dict] | None,
    equipment: list[dict] | None,
    emotion_state: dict[str, Any] | None,
    attack_stat: str,
) -> dict[str, list[str]]:
    """返回指定攻击属性的加成明细（用于展示）。"""
    import re

    detail: dict[str, list[str]] = {}
    for ab in abilities or []:
        name = str(ab.get("name", ""))
        level = int(ab.get("level", 1) or 1)
        if attack_stat in name or name in attack_stat:
            detail.setdefault(attack_stat, []).append(f"能力[{name}]+{level}")
    for eq in equipment or []:
        effect = str(eq.get("effect", "") or "")
        bonus = _parse_bonus(effect)
        m = re.match(r"([\u4e00-\u9fa5]+)\s*[+-]", effect)
        if bonus and m and m.group(1) == attack_stat:
            detail.setdefault(attack_stat, []).append(f"装备[{eq.get('name', '')}]{bonus:+d}")
    emo = _emotion_name(emotion_state or {})
    if emo and emo in EMOTION_MODIFIERS and attack_stat in EMOTION_MODIFIERS[emo]:
        detail.setdefault(attack_stat, []).append(f"情绪[{emo}]{EMOTION_MODIFIERS[emo][attack_stat]:+d}")
    return detail
