"""通用联网搜索与对话导出 API（供主对话页使用）。"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.characters.websearch import web_search
from src.config import BASE_DIR

logger = logging.getLogger("web.search")

router = APIRouter(prefix="/api/web", tags=["web"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


class ExportChatRequest(BaseModel):
    title: str = "对话记录"
    markdown: str = Field(min_length=1)


@router.post("/search")
async def search_api(body: SearchRequest):
    """联网搜索（必应优先，维基百科兜底）。"""
    results = await web_search(body.query)
    return {"success": True, "results": results}


@router.post("/chat/export")
async def export_chat_api(body: ExportChatRequest):
    """把对话文档保存到 E 盘对话记录目录，返回路径。"""
    out_dir = Path(BASE_DIR) / "对话记录"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|\r\n]', "_", body.title).strip() or "对话记录"
        path = out_dir / f"{safe}-对话记录.md"
        path.write_text(body.markdown, encoding="utf-8")
        logger.info(f"对话文档已保存: {path}")
        return {"success": True, "path": str(path)}
    except OSError as e:
        logger.error(f"保存对话文档失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")

