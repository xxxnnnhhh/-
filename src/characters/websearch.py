"""联网搜索 — 必应（带 Cookie，多次重试）+ 维基百科 API 兜底。

网络环境说明：本机直连必应/百度常被验证码或连接错误拦截，
因此采用多通道：必应直连/代理轮流尝试（验证码偶发，重试可命中），
全部失败时退回维基百科 API（走代理，稳定无验证码）。
"""
from __future__ import annotations

import asyncio
import html as html_mod
import json
import logging
import re

import httpx

logger = logging.getLogger("characters.websearch")

PROXY = "http://127.0.0.1:7897"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return html_mod.unescape(text).strip()


async def _client(proxy: str | None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=12,
        follow_redirects=True,
        proxy=proxy,
        headers=HEADERS,
    )


async def _bing_search(query: str, max_results: int) -> list[dict]:
    """必应搜索：带 Cookie 流程，直连/代理各重试多次（验证码偶发）。"""
    params = {"q": query, "setlang": "zh-hans"}
    attempts = [(None, 3), (PROXY, 2)]  # (proxy, tries)
    for proxy, tries in attempts:
        for attempt in range(tries):
            try:
                async with await _client(proxy) as cli:
                    try:
                        await cli.get("https://www.bing.com/", timeout=8)
                    except Exception:
                        pass
                    resp = await cli.get(
                        "https://www.bing.com/search", params=params
                    )
                    resp.raise_for_status()
                    text = resp.text
            except Exception as e:
                logger.debug(f"必应尝试失败（proxy={bool(proxy)}, {attempt}）: {e}")
                continue
            results = []
            for item in re.findall(r'<li class="b_algo".*?</li>', text, re.S)[:max_results]:
                m = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', item, re.S)
                if not m:
                    continue
                url = html_mod.unescape(m.group(1))
                title = _clean(m.group(2))
                if not title or url.startswith("javascript:"):
                    continue
                sm = re.search(r"<p[^>]*>(.*?)</p>", item, re.S)
                snippet = _clean(sm.group(1)) if sm else ""
                results.append({"title": title, "url": url, "snippet": snippet})
            if results:
                logger.info(
                    f"必应搜索「{query[:30]}」命中 {len(results)} 条"
                    f"（proxy={bool(proxy)}, try={attempt + 1}）"
                )
                return results
            await asyncio.sleep(0.5)
    return []


async def _wiki_search(query: str, max_results: int) -> list[dict]:
    """维基百科 API（走代理，稳定）：标题 + 引言摘要。"""
    api = "https://zh.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "srlimit": str(max_results),
    }
    try:
        async with await _client(PROXY) as cli:
            resp = await cli.get(api, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"维基百科搜索失败: {e}")
        return []
    hits = (data.get("query", {}) or {}).get("search", []) or []
    if not hits:
        return []
    titles = [h.get("title", "") for h in hits if h.get("title")]
    results = [
        {
            "title": title,
            "url": f"https://zh.wikipedia.org/wiki/{title.replace(' ', '_')}",
            "snippet": h.get("snippet", ""),
        }
        for h, title in zip(hits, titles)
    ]
    # 取前 2 条的正文引言
    try:
        async with await _client(PROXY) as cli:
            resp = await cli.get(
                api,
                params={
                    "action": "query",
                    "prop": "extracts",
                    "exintro": "1",
                    "explaintext": "1",
                    "titles": "|".join(titles[:2]),
                    "format": "json",
                },
            )
            pages = (resp.json().get("query", {}) or {}).get("pages", {}) or {}
        extracts = {
            p.get("title"): (p.get("extract") or "")[:400]
            for p in pages.values()
            if p.get("extract")
        }
        for r in results:
            if r["title"] in extracts:
                r["snippet"] = extracts[r["title"]]
    except Exception as e:
        logger.debug(f"维基百科引言获取失败: {e}")
    logger.info(f"维基百科搜索「{query[:30]}」返回 {len(results)} 条")
    return results


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """搜索并返回 [{title, url, snippet}]：必应优先，维基百科兜底。"""
    if not query.strip():
        return []
    results = await _bing_search(query, max_results)
    source = "bing"
    if not results:
        results = await _wiki_search(query, max_results)
        source = "wikipedia"
    if not results:
        logger.warning(f"联网搜索失败（{query[:30]}）：所有通道均无结果")
    for r in results:
        r["source"] = source
    return results

