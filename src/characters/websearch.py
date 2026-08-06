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
import urllib.parse

import httpx

logger = logging.getLogger("characters.websearch")

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


async def _client(proxy: str | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=12,
        follow_redirects=True,
        proxy=proxy,
        headers=HEADERS,
    )


def _baidu_decode(url: str) -> str:
    """百度结果链接是 /link?url=... 跳转，直接还原成可点击的原始地址。"""
    m = re.search(r"[?&]url=([^&]+)", url)
    if m:
        decoded = urllib.parse.unquote(m.group(1))
        if decoded.startswith("http://") or decoded.startswith("https://"):
            return decoded
    # 搜狗等站点返回 /link?url=... 这种相对链接，拼接完整地址
    if url.startswith("/link?"):
        return "https://www.sogou.com" + url
    if url.startswith("//"):
        return "https:" + url
    return url


async def _baidu_search(query: str, max_results: int) -> list[dict]:
    """百度搜索：国内直连，无需代理。"""
    params = {"wd": query, "ie": "utf-8"}
    try:
        async with await _client() as cli:
            resp = await cli.get("https://www.baidu.com/s", params=params)
            resp.raise_for_status()
            text = resp.text
    except Exception as e:
        logger.debug(f"百度搜索失败: {e}")
        return []

    results: list[dict] = []
    seen: set[str] = set()
    for item in re.findall(r'<div[^>]*class="[^"]*result[^"]*"[^>]*>.*?</div>', text, re.S)[: max_results * 2]:
        m_title = re.search(r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', item, re.S)
        if not m_title:
            continue
        raw_url = html_mod.unescape(m_title.group(1))
        title = _clean(m_title.group(2))
        if not title:
            continue
        url = _baidu_decode(raw_url)
        if url in seen:
            continue
        seen.add(url)
        m_snip = re.search(r'<span class="content-right_8Zs40">(.*?)</span>', item, re.S) or \
            re.search(r'<div class="c-abstract[^"]*"[^>]*>(.*?)</div>', item, re.S)
        snippet = _clean(m_snip.group(1)) if m_snip else ""
        if not snippet:
            m_snip2 = re.search(r'<span[^>]*class="[^"]*"[^>]*>(.*?)</span>', item, re.S)
            snippet = _clean(m_snip2.group(1)) if m_snip2 else ""
        results.append({"title": title, "url": url, "snippet": snippet[:200]})
        if len(results) >= max_results:
            break
    if results:
        logger.info(f"百度搜索「{query[:30]}」命中 {len(results)} 条")
    return results


async def _sogou_search(query: str, max_results: int) -> list[dict]:
    """搜狗搜索：国内直连，无需代理；偶发反爬页时重试。"""
    params = {"query": query}
    for attempt in range(3):
        try:
            async with await _client() as cli:
                resp = await cli.get("https://www.sogou.com/web", params=params)
                resp.raise_for_status()
                text = resp.text
        except Exception as e:
            logger.debug(f"搜狗搜索失败（{attempt}）: {e}")
            await asyncio.sleep(1.0)
            continue
        if "antispider" in text or "seccode" in text:
            logger.debug(f"搜狗反爬页（{attempt}），稍后重试")
            await asyncio.sleep(1.5)
            continue
        results: list[dict] = []
        for item in re.findall(r'<div[^>]*class="[^"]*vrwrap[^"]*"[^>]*>.*?</div>', text, re.S)[: max_results * 2]:
            m_title = re.search(r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', item, re.S)
            if not m_title:
                continue
            raw_url = html_mod.unescape(m_title.group(1))
            title = _clean(m_title.group(2))
            if not title:
                continue
            # 搜狗结果链接是 /link?url=...，还原成可点击地址
            url = _baidu_decode(raw_url)
            m_snip = re.search(r'<div class="text-layout[^"]*"[^>]*>(.*?)</div>', item, re.S) or \
                re.search(r'<p class="star-wiki"[^>]*>(.*?)</p>', item, re.S)
            snippet = _clean(m_snip.group(1)) if m_snip else ""
            results.append({"title": title, "url": url, "snippet": snippet[:200]})
            if len(results) >= max_results:
                break
        if results:
            logger.info(f"搜狗搜索「{query[:30]}」命中 {len(results)} 条")
            return results
    return []


async def _bing_search(query: str, max_results: int) -> list[dict]:
    """必应搜索：直连重试（国内部分地区可直连）。"""
    params = {"q": query, "setlang": "zh-hans"}
    for attempt in range(2):
        try:
            async with await _client() as cli:
                try:
                    await cli.get("https://cn.bing.com/", timeout=8)
                except Exception:
                    pass
                resp = await cli.get("https://cn.bing.com/search", params=params)
                resp.raise_for_status()
                text = resp.text
        except Exception as e:
            logger.debug(f"必应尝试失败（{attempt}）: {e}")
            await asyncio.sleep(0.5)
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
            logger.info(f"必应搜索「{query[:30]}」命中 {len(results)} 条")
            return results
    return []


async def _wiki_search(query: str, max_results: int) -> list[dict]:
    """维基百科 API（直连，国内不可用时自动跳过）：标题 + 引言摘要。"""
    api = "https://zh.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "srlimit": str(max_results),
    }
    try:
        async with await _client() as cli:
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
        async with await _client() as cli:
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
    """搜索并返回 [{title, url, snippet}]：国内直连优先（百度→必应→搜狗），维基百科兜底。"""
    if not query.strip():
        return []
    channels: list[tuple[str, str]] = [
        ("sogou", await _sogou_search(query, max_results)),
        ("baidu", await _baidu_search(query, max_results)),
        ("bing", await _bing_search(query, max_results)),
    ]
    results: list[dict] = []
    source = "baidu"
    for name, r in channels:
        if r:
            results, source = r, name
            break
    if not results:
        results = await _wiki_search(query, max_results)
        source = "wikipedia"
    if not results:
        logger.warning(f"联网搜索失败（{query[:30]}）：所有通道均无结果")
    for r in results:
        r["source"] = source
    return results
