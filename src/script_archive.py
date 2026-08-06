"""脚本本地存档：把脚本库脚本导出为中文标注的 Markdown 存档（E 盘）。

存档目录可通过设置页修改（SCRIPT_ARCHIVE_DIR），默认 E:\\故事机器\\脚本存档。
每个脚本一个文件：<存档目录>/<分组>/<脚本名>.md
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from src.config import SCRIPT_ARCHIVE_DIR, SCRIPT_LIBRARY_DIR
from src.workflow.script_library import get_script_library

logger = logging.getLogger("script_archive")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def archive_script(group: str, script_name: str) -> Path:
    """把脚本库中的某个脚本生成为中文标注的 Markdown 存档，返回存档路径。"""
    catalog = get_script_library()
    ext_map = {"shell": "sh", "python": "py"}
    script_type = "python"
    content = ""
    meta = ""

    # 尝试读取脚本内容（自动探测类型）
    for t, ext in ext_map.items():
        try:
            location = catalog.resolve_file(group, script_name, f"{script_name}.{ext}")
            if location is not None:
                p = location.directory / f"{script_name}.{ext}"
                if p.exists():
                    script_type = t
                    content = p.read_text(encoding="utf-8")
                    break
        except Exception:
            continue

    # 读取 SCRIPT.md 元信息
    try:
        meta_loc = catalog.resolve_file(group, script_name, "SCRIPT.md")
        if meta_loc is not None:
            mp = meta_loc.directory / "SCRIPT.md"
            if mp.exists():
                meta = mp.read_text(encoding="utf-8")
    except Exception:
        pass

    if not content and not meta:
        raise FileNotFoundError(f"脚本不存在: {group}/{script_name}")

    out_dir = SCRIPT_ARCHIVE_DIR / group
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{script_name}.md"

    lines = [
        f"# 脚本存档：{script_name}",
        "",
        f"- 分组：{group}",
        f"- 脚本名：{script_name}",
        f"- 类型：{script_type}",
        f"- 存档时间：{_now()}",
        f"- 存档位置：{out_path}",
        "",
    ]
    if meta.strip():
        lines += ["## 描述（SCRIPT.md）", "", meta.strip(), ""]
    if content.strip():
        code_block = "python" if script_type == "python" else "bash"
        lines += [f"## 代码（.{ext_map[script_type]}）", "", f"```{code_block}", content.rstrip(), "```", ""]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"脚本已存档: {out_path}")
    return out_path


def archive_all() -> list[Path]:
    """为脚本库中所有脚本生成存档，返回存档路径列表。"""
    catalog = get_script_library()
    written: list[Path] = []
    for item in catalog.list_scripts():
        group = item.get("group", "")
        name = item.get("name", "")
        if not group or not name:
            continue
        try:
            written.append(archive_script(group, name))
        except Exception as e:
            logger.warning(f"脚本存档失败: {group}/{name}: {e}")
    return written


def list_archives() -> list[dict]:
    """列出所有已存档脚本（中文标注）。"""
    result: list[dict] = []
    if not SCRIPT_ARCHIVE_DIR.exists():
        return result
    for group_dir in sorted(p for p in SCRIPT_ARCHIVE_DIR.iterdir() if p.is_dir()):
        for md in sorted(group_dir.glob("*.md")):
            result.append({
                "group": group_dir.name,
                "name": md.stem,
                "path": str(md),
                "size": md.stat().st_size,
                "updated_at": datetime.fromtimestamp(md.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
    return result


def get_archive_path(group: str, script_name: str) -> Path | None:
    """查找某个脚本的存档路径。"""
    p = SCRIPT_ARCHIVE_DIR / group / f"{script_name}.md"
    return p if p.exists() else None


def export_all_markdown() -> str:
    """把所有脚本存档合并为一个 Markdown 文档（用于网页导出全部）。"""
    parts = ["# 脚本库全部存档", ""]
    for item in list_archives():
        p = Path(item["path"])
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
            parts.append("")
    return "\n".join(parts)
