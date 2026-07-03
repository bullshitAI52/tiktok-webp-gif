"""TikTok 评论区动图提取 + WebP → GIF 转换核心模块

用法（在服务器上）:
    pip install streamlit pillow requests yt-dlp
    streamlit run app.py --server.port 8501
"""

import io
import json
import logging
import re
import subprocess
import time

import requests
from PIL import Image

logger = logging.getLogger(__name__)

# ─── 常量 ───────────────────────────────────────────────

WECHAT_MAX_BYTES = 4.5 * 1024 * 1024      # 微信自定义表情包上限 ≈ 4.5 MB
WECHAT_TARGET_BYTES = 1.5 * 1024 * 1024   # 上传/发送最舒服的大小

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
    "Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 "
    "Safari/537.36"
)

STICKER_DOMAINS = [
    "p16-va-default", "p16-sign", "p16-va", "p26-va",
    "~tplv", "dy-360p", "dy-480p",
]


# ─── 链接解析 ──────────────────────────────────────────

def parse_video_id(url: str) -> str | None:
    """从 TikTok 链接提取视频 ID。"""
    url = url.strip().split("?")[0]

    # https://www.tiktok.com/@user/video/1234567890
    m = re.search(r"/video/(\d+)", url)
    if m:
        return m.group(1)

    # https://vm.tiktok.com/XXXXXX/
    m = re.search(r"vm\.tiktok\.com/(\w+)", url)
    if m:
        return m.group(1)

    # https://www.tiktok.com/t/ZTYxMjM0/
    m = re.search(r"/t/(\w+)", url)
    if m:
        return m.group(1)

    return None


def resolve_short_url(url: str) -> str:
    """解析 vm.tiktok.com 短链。"""
    try:
        r = requests.head(url, allow_redirects=True, timeout=10,
                          headers={"User-Agent": MOBILE_UA})
        return r.url
    except Exception:
        return url


def make_session() -> requests.Session:
    """创建带 ttwid cookie 的 Session。"""
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": DESKTOP_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://www.tiktok.com",
        "Referer": "https://www.tiktok.com/",
    })
    # 先访问首页拿 cookie
    try:
        sess.get("https://www.tiktok.com/", timeout=20)
    except Exception:
        pass
    return sess


# ─── 视频元数据 ────────────────────────────────────────

def get_video_meta(url: str) -> dict:
    """通过 yt-dlp 获取视频元数据。返回 dict，包含 id / title 等。"""
    cmd = ["yt-dlp", "--dump-json", "--no-download", "--quiet", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"yt-dlp 解析失败 (err={r.returncode}): {r.stderr[:200]}")
        return json.loads(r.stdout.strip().splitlines()[0])
    except FileNotFoundError:
        raise RuntimeError("请先在服务器安装 yt-dlp: pip install yt-dlp")


# ─── 评论区贴纸抓取 ────────────────────────────────────

def fetch_comment_stickers(
    video_id: str,
    max_count: int = 80,
    max_pages: int = 3,
) -> list[dict]:
    """抓取评论区带动图贴纸的评论，返回 [{url, comment_text, author}, ...]。"""
    stickers: list[dict] = []
    seen: set[str] = set()
    sess = make_session()
    cursor = 0
    n_pages = 0

    while n_pages < max_pages:
        params = {
            "aweme_id": video_id,
            "count": min(max_count, 50),
            "cursor": cursor,
        }
        try:
            resp = sess.get(
                "https://www.tiktok.com/api/comment/list/",
                params=params, timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("评论 API 返回 %s，停止", resp.status_code)
                break

            data = resp.json()
            comments = data.get("comments", [])
            if not comments:
                break

            for c in comments:
                sticker = c.get("sticker_data") or {}
                image_url = (
                    sticker.get("image_url")
                    or sticker.get("image")
                    or c.get("sticker_url")
                    or ""
                )
                if not image_url:
                    continue

                # 只保留 .webp / .gif
                clean = image_url.split("?")[0].split("#")[0]
                if not clean.lower().endswith((".webp", ".gif")):
                    continue
                if clean in seen:
                    continue
                seen.add(clean)

                stickers.append({
                    "url": clean,
                    "comment_text": c.get("text", ""),
                    "author": c.get("user", {}).get("nickname", ""),
                })

            cursor = data.get("cursor", cursor + len(comments))
            if not data.get("has_more", False):
                break
            n_pages += 1
            time.sleep(0.5)

        except Exception as e:
            logger.warning("抓取评论异常: %s", e)
            break

    return stickers


# ─── WebP → GIF 转换 ───────────────────────────────────

def convert_webp_to_gif(
    image_data: bytes,
    max_size: int = WECHAT_MAX_BYTES,
) -> bytes:
    """把 WebP 动图转成微信友好的 GIF（自动降采样控制体积）。"""
    src = Image.open(io.BytesIO(image_data))
    is_animated = getattr(src, "is_animated", False)
    n_frames = getattr(src, "n_frames", 1)

    # ─ 逐帧读取 ─
    frames: list[Image.Image] = []
    durations: list[int] = []
    for i in range(n_frames):
        src.seek(i)
        frames.append(src.convert("RGBA"))
        try:
            dur = src.info.get("duration", 100)
        except Exception:
            dur = 100
        durations.append(max(dur, 20))

    if not frames:
        frames = [src.convert("RGBA")]
        durations = [100]

    # ─ 降采样到合理尺寸 ─
    MAX_DIM = 480
    resized = []
    for f in frames:
        w, h = f.size
        if max(w, h) > MAX_DIM:
            s = MAX_DIM / max(w, h)
            f = f.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
        resized.append(f)

    # ─ 如果体积仍超限，持续缩小 ─
    w, h = resized[0].size
    for _attempt in range(6):
        buf = io.BytesIO()
        resized[0].save(
            buf, format="GIF",
            save_all=True,
            append_images=resized[1:] if len(resized) > 1 else [],
            loop=0, duration=durations, disposal=2,
        )
        if buf.tell() <= max_size:
            return buf.getvalue()
        # 缩小 80%
        w, h = max(32, int(w * 0.8)), max(32, int(h * 0.8))
        resized = [f.resize((w, h), Image.LANCZOS) for f in resized]

    # ─ 最后尝试 ─
    buf = io.BytesIO()
    resized[0].save(
        buf, format="GIF",
        save_all=True,
        append_images=resized[1:] if len(resized) > 1 else [],
        loop=0, duration=durations, disposal=1,
    )
    return buf.getvalue()


# ─── 一站式入口 ────────────────────────────────────────

def harvest(tiktok_url: str) -> list[dict]:
    """输入 TikTok 链接 → 返回 [{url, gif_bytes, gif_size_kb, comment_text}, ...]。"""
    # 短链解析
    if "vm.tiktok.com" in tiktok_url or "/t/" in tiktok_url:
        tiktok_url = resolve_short_url(tiktok_url)

    video_id = parse_video_id(tiktok_url)
    if not video_id:
        raise ValueError("无法解析视频 ID，请检查链接格式")

    # yt-dlp 确认
    try:
        meta = get_video_meta(tiktok_url)
        actual_id = meta.get("id", video_id)
    except Exception as e:
        logger.warning("yt-dlp 失败，回退到正则 ID: %s", e)
        actual_id = video_id

    stickers = fetch_comment_stickers(actual_id)
    if not stickers:
        raise ValueError(
            "评论区没找到动图贴纸。可能原因："
            "① 视频评论无人发贴纸；"
            "② TikTok 风控触发（等几分钟再试）"
        )

    results = []
    for s in stickers:
        try:
            resp = requests.get(s["url"], timeout=15,
                                headers={"User-Agent": MOBILE_UA})
            if resp.status_code != 200:
                continue
            gif = convert_webp_to_gif(resp.content)
            results.append({
                **s,
                "gif_bytes": gif,
                "gif_size_kb": round(len(gif) / 1024, 1),
            })
        except Exception as e:
            logger.warning("转换失败: %s | url: %s", e, s["url"][:60])
            continue

    return results
