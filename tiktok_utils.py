"""TikTok 评论区动图提取 — 支持第三方 API + 代理 + Playwright 三种模式

配置方式（按优先级）:
  1. TIKTOK_API_KEY=xxx       # SocialData.tools API Key（推荐，评论区数据来源）
  2. TIKTOK_PROXY=socks5://... # 代理（绕过 IP 封锁）
  3. TIKTOK_WORKER=url         # Cloudflare Worker 中转
"""

import io
import json
import logging
import os
import re
import subprocess
import time

import requests
from PIL import Image

logger = logging.getLogger(__name__)

# ─── 常量 ───────────────────────────────────────────────
WECHAT_MAX_BYTES = 4.5 * 1024 * 1024
WECHAT_TARGET_BYTES = 1.5 * 1024 * 1024
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"

# ─── 配置（环境变量） ──────────────────────────────────
TIKTOK_API_KEY = os.environ.get("TIKTOK_API_KEY", "")
TIKTOK_PROXY = os.environ.get("TIKTOK_PROXY", "")
TIKTOK_WORKER = os.environ.get("TIKTOK_WORKER", "")


def _proxies() -> dict:
    if TIKTOK_PROXY:
        return {"http": TIKTOK_PROXY, "https": TIKTOK_PROXY}
    return {}

def _headers(extra: dict = None) -> dict:
    h = {"User-Agent": MOBILE_UA}
    if extra:
        h.update(extra)
    return h


# ─── 链接解析 ──────────────────────────────────────────
def parse_video_id(url: str) -> str | None:
    url = url.strip().split("?")[0]
    for pattern in [r"/video/(\d+)", r"vm\.tiktok\.com/(\w+)", r"/t/(\w+)"]:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def resolve_short_url(url: str) -> str:
    try:
        r = requests.get(url, timeout=15, headers=_headers(),
                         proxies=_proxies(), allow_redirects=True)
        return r.url
    except Exception:
        return url


# ─── 模式 1: 第三方 API（SocialData.tools） ──────────
SOCIALDATA_BASE = "https://api.socialdata.tools/tiktok"

def _fetch_comments_via_api(video_id: str, max_count: int = 50) -> list[dict]:
    """通过 SocialData.tools API 获取评论（含 sticker 数据）"""
    stickers: list[dict] = []
    seen_urls: set[str] = set()
    cursor = 0

    for page in range(3):
        try:
            resp = requests.get(
                f"{SOCIALDATA_BASE}/video/{video_id}/comments",
                params={"cursor": cursor, "count": min(max_count, 50)},
                headers={"Authorization": f"Bearer {TIKTOK_API_KEY}"},
                timeout=20,
            )
            if resp.status_code != 200:
                logger.warning("API 返回 %s: %s", resp.status_code, resp.text[:200])
                break

            data = resp.json()
            comments = data.get("comments", [])
            if not comments:
                break

            for c in comments:
                sticker = c.get("sticker_data") or {}
                image_url = sticker.get("image_url") or sticker.get("image") or c.get("sticker_url") or ""
                if not image_url:
                    continue
                clean = image_url.split("?")[0].split("#")[0]
                if not clean.lower().endswith((".webp", ".gif")):
                    continue
                if clean in seen_urls:
                    continue
                seen_urls.add(clean)
                stickers.append({
                    "url": clean,
                    "comment_text": c.get("text", ""),
                    "author": c.get("user", {}).get("nickname", ""),
                })

            cursor = data.get("cursor", cursor + len(comments))
            if not data.get("has_more", False):
                break

        except Exception as e:
            logger.warning("API 调用异常: %s", e)
            break

    return stickers


# ─── 模式 2: Playwright + 代理（浏览器爬取） ─────────
def _playwright_harvest(video_id: str) -> list[dict]:
    """通过 Playwright + xvfb + 代理加载页面 → 提取 sticker"""
    stickers: list[dict] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright 未安装")
        return stickers

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False,
            args=["--no-sandbox", "--disable-gpu"])
        ctx = browser.new_context(
            proxy={"server": TIKTOK_PROXY} if TIKTOK_PROXY else None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
        )
        page = ctx.new_page()

        try:
            page.goto(f"https://www.tiktok.com/@x/video/{video_id}",
                       wait_until="domcontentloaded", timeout=45000)
            time.sleep(5)

            # 截取 API 响应
            api_responses = []
            def capture(resp):
                if "api/comment/list" in resp.url:
                    api_responses.append(resp)
            page.on("response", capture)

            # 滚动触发评论加载
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 500)")
                time.sleep(2)
            time.sleep(3)

            # 从捕获的响应中提取
            for resp in api_responses:
                try:
                    data = resp.json()
                    for c in data.get("comments", []):
                        sticker = c.get("sticker_data") or {}
                        url = sticker.get("image_url") or ""
                        if url:
                            stickers.append({
                                "url": url.split("?")[0],
                                "comment_text": c.get("text", ""),
                                "author": c.get("user", {}).get("nickname", ""),
                            })
                except Exception:
                    pass

            # 尝试直接从页面 HTML 提取
            if not stickers:
                html = page.content()
                for m in re.finditer(r'data-e2e="comment-item".*?data-src="(https://[^"]+\.(webp|gif))"', html):
                    stickers.append({"url": m.group(1), "comment_text": "", "author": ""})

        except Exception as e:
            logger.warning("Playwright 提取异常: %s", e)
        finally:
            browser.close()

    return stickers


# ─── WebP → GIF 转换 ───────────────────────────────────
def convert_webp_to_gif(image_data: bytes, max_size: int = WECHAT_MAX_BYTES) -> bytes:
    src = Image.open(io.BytesIO(image_data))
    n_frames = getattr(src, "n_frames", 1)
    frames, durations = [], []
    for i in range(n_frames):
        src.seek(i)
        frames.append(src.convert("RGBA"))
        durations.append(max(src.info.get("duration", 100), 20))

    # 降采样
    MAX_DIM = 480
    resized = []
    for f in frames:
        w, h = f.size
        if max(w, h) > MAX_DIM:
            s = MAX_DIM / max(w, h)
            f = f.resize((max(1, int(w*s)), max(1, int(h*s))), Image.LANCZOS)
        resized.append(f)

    # 压缩到 max_size 以内
    w, h = resized[0].size
    for _ in range(6):
        buf = io.BytesIO()
        resized[0].save(buf, format="GIF", save_all=True,
                        append_images=resized[1:] if len(resized) > 1 else [],
                        loop=0, duration=durations, disposal=2)
        if buf.tell() <= max_size:
            return buf.getvalue()
        w, h = max(32, int(w*0.8)), max(32, int(h*0.8))
        resized = [f.resize((w, h), Image.LANCZOS) for f in resized]

    buf = io.BytesIO()
    resized[0].save(buf, format="GIF", save_all=True,
                    append_images=resized[1:] if len(resized) > 1 else [],
                    loop=0, duration=durations, disposal=1)
    return buf.getvalue()


# ─── 一站式入口 ────────────────────────────────────────
def harvest(tiktok_url: str) -> list[dict]:
    if "vm.tiktok.com" in tiktok_url or "/t/" in tiktok_url:
        tiktok_url = resolve_short_url(tiktok_url)

    video_id = parse_video_id(tiktok_url)
    if not video_id:
        raise ValueError("无法解析视频 ID")

    # 用 yt-dlp 获取准确的 aweme_id
    try:
        meta = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", "--quiet", tiktok_url],
            capture_output=True, text=True, timeout=60)
        if meta.returncode == 0:
            actual_id = json.loads(meta.stdout.strip().splitlines()[0]).get("id", video_id)
        else:
            actual_id = video_id
    except Exception:
        actual_id = video_id

    # ── 模式选择 ──
    stickers = []

    # 模式 1: 第三方 API
    if TIKTOK_API_KEY:
        logger.info("Using SocialData.tools API")
        stickers = _fetch_comments_via_api(actual_id)

    # 模式 2: Playwright + 代理
    elif TIKTOK_PROXY:
        logger.info("Using Playwright + proxy")
        stickers = _playwright_harvest(actual_id)

    if not stickers:
        raise ValueError(
            "评论区没找到动图贴纸。\n"
            "可能原因：该视频评论无人发贴纸。\n"
            "如需绕过 TikTok 风控，配置 TIKTOK_API_KEY 即可。"
        )

    # 下载并转换
    results = []
    sess = requests.Session()
    sess.proxies.update(_proxies())
    for s in stickers:
        try:
            resp = sess.get(s["url"], timeout=15, headers=_headers())
            if resp.status_code != 200:
                continue
            gif = convert_webp_to_gif(resp.content)
            results.append({
                **s,
                "gif_bytes": gif,
                "gif_size_kb": round(len(gif) / 1024, 1),
            })
        except Exception as e:
            logger.warning("转换失败: %s", e)
            continue

    return results
