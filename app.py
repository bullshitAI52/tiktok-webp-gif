"""TikTok 动图 → 微信直传工具 — 手机优先的 Streamlit 前端"""

import logging

import streamlit as st

from tiktok_utils import harvest, WECHAT_TARGET_BYTES

logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="微信动图收割机",
    page_icon="🎭",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ─── 手机优先 CSS ─────────────────────────────────────
st.markdown(
    """
<style>
/* 整体容器适配手机窄屏 */
.block-container {
    padding: 1rem 0.8rem !important;
    max-width: 480px !important;
}
/* 标题 */
h1 {
    font-size: 1.4rem !important;
    line-height: 1.3;
    margin-bottom: 0.3rem !important;
}
/* 输入框和按钮 */
.stTextInput > div > input {
    font-size: 16px !important;
    padding: 12px 14px !important;
    border-radius: 10px !important;
    min-height: 48px;
}
.stButton > button {
    font-size: 16px !important;
    font-weight: 600;
    padding: 10px 0 !important;
    border-radius: 10px !important;
    min-height: 48px;
}
/* 图片 — 全宽显示 */
div[data-testid="stImage"] {
    width: 100% !important;
    margin: 0.5rem 0;
}
div[data-testid="stImage"] img {
    width: 100% !important;
    height: auto !important;
    max-height: none !important;
    border-radius: 12px;
    object-fit: contain;
}
/* 下载按钮 */
.stDownloadButton > button {
    font-size: 15px !important;
    padding: 10px 0 !important;
    border-radius: 10px !important;
    min-height: 44px;
}
/* 提示气泡内的文字分行 */
.stInfo, .stSuccess {
    font-size: 14px;
    line-height: 1.6;
}
/* 分割线和卡片间距 */
hr {
    margin: 1rem 0 !important;
}
/* 状态指示器缩紧 */
.stStatusWidget {
    font-size: 14px;
}
/* 隐藏 Streamlit 默认品牌 */
#MainMenu {visibility: hidden;}
footer {display: none !important;}
</style>
""",
    unsafe_allow_html=True,
)

# ─── 标题区 ───────────────────────────────────────────
st.title("🎭 TikTok 动图 → 微信")
st.caption(
    "自动转成微信表情包能认的标准 GIF"
)

# ─── 输入区（上下布局，便于手机点击） ────────────────
tiktok_url = st.text_input(
    "TikTok 视频链接",
    placeholder="粘贴 TikTok 链接…",
    label_visibility="collapsed",
)

go = st.button("🚀 收割并转成 GIF", type="primary", use_container_width=True)


# ─── 处理逻辑 ─────────────────────────────────────────
if go and tiktok_url:
    with st.status("工作中… 需 10-20 秒", expanded=True) as status:
        try:
            st.write("📡 解析链接…")
            results = harvest(tiktok_url)

            status.update(
                label=f"✅ 搞定！{len(results)} 张动图",
                state="complete",
                expanded=True,
            )
        except ValueError as e:
            st.error(str(e))
            st.info(
                "💡 换个评论区有动图贴纸的热门视频试试"
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
                "可能是 TikTok 风控拦截，等几分钟再试"
            )
            status.update(state="error")
            st.stop()

    # ─── 展示结果（纯垂直布局，手机友好） ────────────
    if results:
        st.success(
            f"共 {len(results)} 张，已控制在 "
            f"{WECHAT_TARGET_BYTES // 1024 // 1024}MB 以内"
        )

        for i, r in enumerate(results):
            # 图片 — 全宽
            st.image(r["gif_bytes"])

            # 信息行
            info = []
            info.append(f"📦 {r['gif_size_kb']:.0f} KB")
            if r["comment_text"]:
                info.append(f"💬 {r['comment_text'][:50]}")
            if r["author"]:
                info.append(f"👤 {r['author'][:20]}")
            st.caption("  ·  ".join(info))

            # 下载按钮
            col_dl, _ = st.columns([1, 2])
            with col_dl:
                st.download_button(
                    label="💾 保存",
                    data=r["gif_bytes"],
                    file_name=f"wx_gif_{i+1}.gif",
                    mime="image/gif",
                    use_container_width=True,
                )

            st.divider()

        # 手机使用提示
        st.info(
            "📱 **如何发微信**\n\n"
            "长按上方动图 → **拷贝** → 切到微信 → **粘贴** 发送\n\n"
            "在微信里再次长按已发送的图 → **添加** → 永久存入表情库"
        )
else:
    # ─── 默认指引（手机上更简洁） ────────────────────
    st.markdown("---")
    st.markdown(
        "**①** 找一条评论区有沙雕动图的 TikTok 视频\n\n"
        "**②** 复制链接，粘贴到上面的输入框，点「收割」\n\n"
        "**③** 长按动图 → 拷贝 → 切微信粘贴发送 ✅"
    )

    st.caption(f"v1.0 · 部署在 107.172.32.153:8501")
