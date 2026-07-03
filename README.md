# 🎭 TikTok → 微信动图收割机

把 TikTok 评论区里的动图贴纸一键收割，转成微信自定义表情包能用的标准 GIF。

## 一键部署

### 1. 在 VPS 上装依赖

```bash
pip install -r requirements.txt
```

> 如果没装 yt-dlp 也可以用 `pip install yt-dlp` 或 `brew install yt-dlp`

### 2. 启动

```bash
streamlit run app.py --server.port 8501
```

如果你用了 Nginx / 反向代理，记得把 `--server.enableCORS false` 也加上。

### 3. 手机端访问

用 iPhone Safari（或安卓 Chrome）打开 `http://你的服务器IP:8501`

## 使用流程

1. 找个 TikTok 视频（评论区有人发动图贴纸那种最好）
2. 复制链接，粘贴到网页输入框
3. 点「🚀 收割」，等 10-20 秒
4. **长按动图 → 拷贝 → 切到微信 → 粘贴 → 发送 ✅**
5. 在微信长按已发送的图 →「添加」→ 永久存入自定义表情库

## 注意事项

- 微信自定义表情包单张限制 **≤ 5MB**，本工具自动控制在 **1.5MB 左右**
- TikTok API 可能触发风控，如果频繁失败可以在服务器上跑 `curl https://www.tiktok.com` 验证连通性
- 默认监听 8501 端口，可通过 `--server.port` 修改
- 建议用 Nginx 加 HTTPS 反代（iOS 某些功能需要安全上下文）

## 文件结构

```
├── app.py            # Streamlit 前端界面
├── tiktok_utils.py   # 核心逻辑：链接解析、评论抓取、WebP→GIF 转换
├── requirements.txt  # Python 依赖
└── README.md         # 你正在看的这个
```
