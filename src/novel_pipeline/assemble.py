"""全文合成：把每一章 story/XXXX/chapter.md 合并成完整文本并 E 盘存档。"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from .models import NOVEL_ARCHIVE_DIR, _safe_filename, zero_pad_chapter

if TYPE_CHECKING:
    from .models import NovelProject

logger = logging.getLogger(__name__)


def assemble_full_text(project: "NovelProject") -> tuple[str, str]:
    """合并章节为完整文本。

    Returns:
        (工作区内的完整文本路径, E 盘存档路径)
    """
    ws = Path(project.workspace)
    title = _safe_filename(project.name or project.project_id)
    parts = [
        f"# 《{title}》",
        "",
        f"类型：{project.genre or '未设置'}　语言：{project.language or '中文'}",
        "",
    ]
    for ch in project.chapters:
        ch_num = zero_pad_chapter(ch)
        chapter_md = ws / "story" / ch_num / "chapter.md"
        heading = f"## 第{int(ch)}章"
        if chapter_md.is_file():
            text = chapter_md.read_text(encoding="utf-8").strip()
            parts.append(f"---\n\n{heading}\n\n{text}")
        else:
            parts.append(f"---\n\n{heading}\n\n（本章正文缺失：{chapter_md}）")

    full_text = "\n\n".join(parts).rstrip() + "\n"

    # 1. 工作区内副本（供网页预览/下载）
    novel_dir = ws / "novel"
    novel_dir.mkdir(parents=True, exist_ok=True)
    final_path = novel_dir / f"《{title}》完整文本.md"
    final_path.write_text(full_text, encoding="utf-8")

    # 2. E 盘存档（中文命名，含章节分文件；可用 archive_root 覆盖默认目录）
    archive_root = Path(project.archive_root) if project.archive_root else NOVEL_ARCHIVE_DIR
    archive_root.mkdir(parents=True, exist_ok=True)
    book_dir = archive_root / f"《{title}》"
    book_dir.mkdir(parents=True, exist_ok=True)
    archived = book_dir / f"《{title}》完整文本.md"
    archived.write_text(full_text, encoding="utf-8")

    chapter_dir = book_dir / "章节"
    for ch in project.chapters:
        ch_num = zero_pad_chapter(ch)
        chapter_md = ws / "story" / ch_num / "chapter.md"
        if chapter_md.is_file():
            chapter_dir.mkdir(parents=True, exist_ok=True)
            (chapter_dir / f"第{int(ch)}章.md").write_text(
                chapter_md.read_text(encoding="utf-8"), encoding="utf-8"
            )

    # 顺手把工作区里的 meta / outline / archive 也归档一份，方便复盘
    try:
        for sub in ("meta", "outline", "archive"):
            src = ws / sub
            if src.is_dir():
                dst = book_dir / sub
                dst.mkdir(parents=True, exist_ok=True)
                for f in src.glob("*"):
                    if f.is_file() and f.stat().st_size < 5 * 1024 * 1024:
                        shutil.copy2(f, dst / f.name)
    except Exception:
        logger.exception("归档辅助文件失败（不影响完整文本）")

    logger.info("完整文本已生成: %s | %s", final_path, archived)
    return str(final_path), str(archived)
