"""人物日志文件 — E 盘、按角色名命名的 Markdown 记录。

每个角色的每一场演绎（故事 / 圆桌）和每一段对话都会追加到
`E:\\故事机器\\人物日志\\<角色名>.md`，用户可随时手动删除。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from src.config import BASE_DIR

logger = logging.getLogger("characters.logs")

LOG_DIR = Path(BASE_DIR) / "人物日志"

TYPE_LABELS = {
    "story": "故事演绎",
    "roundtable": "圆桌演绎",
    "chat": "与用户的对话",
}


def _safe_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]', "_", name).strip()
    return cleaned or "未命名角色"


def log_file_for(character_name: str) -> Path:
    return LOG_DIR / f"{_safe_name(character_name)}.md"


def append_log_entry(
    character_name: str,
    entry_type: str,
    title: str,
    content: str,
    timestamp: str | None = None,
) -> str:
    """把一条记录追加到角色日志文件，返回文件路径（失败返回空串）。"""
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    date = ts[:10]
    type_label = TYPE_LABELS.get(entry_type, entry_type)
    path = log_file_for(character_name)
    section = (
        f"\n## {date}｜{type_label}｜{title}\n\n"
        f"{content.strip()}\n"
    )
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(section)
        return str(path)
    except OSError as e:
        logger.error(f"写入角色日志失败 {path}: {e}")
        return ""

