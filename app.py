"""TikTok 动图 → 微信直传工具 — Streamlit 前端

在服务器上跑:
    pip install streamlit pillow requests yt-dlp
    streamlit run app.py --server.port 8501
"""

import io
import logging

import streamlit as st

from tiktok_utils import harvest, WECHAT_TARGET_BYTES

logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="微信动图收割机",
    page_icon="🎭",
    layout="centered",
)

# ─── 页面样式微调 ─────────────────────────────────────
st.markdown(
    """
<style>
.stButton > button { width: 100%; }
div[data-testid="stImage"] img {
    border-radius: 12px;
    max-height: 400px;
    object-fit: contain;
}
</style>
""",
    unsafe_allow_html=True,
)

# ─── 标题区 ───────────────────────────────────────────
st.title("🎭 TikTok → 微信动图收割机")
st.caption(
    "粘贴 TikTok 视频链接，自动收割评论区里的动图贴纸，"
    "转成微信自定义表情包能用的标准 GIF。"
)

# ─── 输入区 ───────────────────────────────────────────
col1, col2 = st.columns([6, 1])
with col1:
    tiktok_url = st.text_input(
        "TikTok 视频链接",
        placeholder="https://www.tiktok.com/@user/video/123...",
        label_visibility="collapsed",
    )
with col2:
    go = st.button("🚀 收割", type="primary", use_container_width=True)


# ─── 处理逻辑 ─────────────────────────────────────────
if go and tiktok_url:
    with st.status("正在干活… 可能需要 10-20 秒", expanded=True) as status:
        try:
            st.write("📡 解析链接中…")
            results = harvest(tiktok_url)
            status.update(
                label=f"✅ 搞定！收割到 {len(results)} 张动图",
                state="complete",
                expanded=True,
            )
        except ValueError as e:
            st.error(str(e))
            st.info(
                "💡 换一个热门视频试试？评论区必须有动图贴纸的才好使。"
            )
            status.update(state="error")
            st.stop()
        except RuntimeError as e:
            st.error(str(e))
            status.update(state="error")
            st.stop()
        except Exception as e:
            st.error(f"出错了: {e}")
            st.info(
                "可能是 TikTok 风控拦截。去服务器上用 "
                "`curl -s https://www.tiktok.com` 验证能不能访问。"
            )
            status.update(state="error")
            st.stop()

    # ─── 展示结果 ─────────────────────────────────────
    if results:
        st.success(
            f"共 {len(results)} 张，全部已转成微信标准 GIF 格式"
            f"（单张控制在 {WECHAT_TARGET_BYTES // 1024 // 1024}MB 以内）"
        )

        for i, r in enumerate(results):
            st.markdown(f"### #{i+1}")
            cols = st.columns([3, 1])

            with cols[0]:
                st.image(r["gif_bytes"])

            with cols[1]:
                st.metric("大小", f"{r['gif_size_kb']:.0f} KB")
                if r["comment_text"]:
                    st.caption(f"💬 {r['comment_text'][:40]}")
                if r["author"]:
                    st.caption(f"👤 {r['author'][:20]}")

                st.download_button(
                    label="💾 保存 GIF",
                    data=r["gif_bytes"],
                    file_name=f"wx_gif_{i+1}.gif",
                    mime="image/gif",
                    use_container_width=True,
                )

            st.divider()

        # 手机端使用提示
        st.info(
            "📱 **手机端用 Safari 打开本页面**，长按图片选「拷贝」，"
            "切到微信粘贴即可直接发送。再次长按选「添加」可永久存入表情库。"
        )
else:
    # 默认展示操作指引
    st.markdown("---")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("**①** 找个 TikTok 视频\n\n评论区有人发搞笑动图的那种")
    with col_b:
        st.markdown("**②** 复制链接，粘贴到上面\n\n点「收割」等十几秒")
    with col_c:
        st.markdown("**③** 长按 → 拷贝 → 发微信\n\n或点 💾 保存到相册")

    st.caption(
        "需要 VPS 且有公网 IP。部署方式见 README.md。"
    )
