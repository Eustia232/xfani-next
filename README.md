# xfani-next

稀饭动漫 **Next 站**（next.xifanacg.com）下载器。旧站（dick.xfani.com 已死）与旧版前端不再支持。

## 工作原理

1. 解析番剧页 `https://next.xifanacg.com/anime/{aid}`（SSR HTML）得到剧集 `episode_id` 列表；
2. 对每集调用 `POST api.xifanacg.com/functions/v1/issue-web-playback`（匿名）拿到全部线路的 mp4 直链，按优先级（默认 AL > xfxf1，实测 AL 约快一倍且同一文件）选择；
3. 流式下载，支持断点续传（`.part` + Range）。

## 使用

```bash
uv sync                                # 安装依赖（Python ≥3.12，uv 自动管理）

uv run xfani --search 胆大党           # 按名字查新版 ID
uv run xfani --list 3397               # 仅解析剧集列表预览
uv run xfani --id 3397                 # 下载整部
uv run xfani --id 3397 --ep 1-3        # 下载指定集
uv run xfani                           # 处理 status/todo.json 队列
uv run xfani --migrate                 # 旧仓库 already.json 标题 → 新 ID 迁移
uv run xfani --refine                  # 对未命中项做二次模糊匹配（difflib + 年份消歧）
uv run pytest                          # 单元测试
```

`python main.py` 与 `uv run xfani` 等价（保留旧习惯；需先激活 .venv 或用 uv run）。

## Windows 部署与批量下载工作流

与旧版 xfani 的习惯一致，只是命令和 ID 体系变了：

1. **装依赖**：`pip install uv` → 仓库目录下 `uv sync`；
2. **自定义下载路径**：编辑 `status/download_config.json` 的 `"path"`（如 `"D:/Eustia/Video"`）；JSON 里 Windows 路径推荐正斜杠 `D:/...`，写单反斜杠 `D:\Eustia\Video` 也能被容错解析（会自动补转义）；
3. **写入 todo**：`status/todo.json` 只填**新版 ID**（如 `["3397"]`，用 `--search` 查；旧版 ID 体系不通用）；
4. **批量下载**：`uv run xfani`（默认处理 todo 队列）；单部直下 `uv run xfani 3397`。

中断重跑会从 `.part` 断点续传，已完成的集与已完成的番（按标题去重）自动跳过。

## 配置（status/download_config.json）

```json
{
    "path": "~/Videos/xfani",               // 保存目录
    "source_priority": ["AL", "xfxf1"]      // 线路优先级
}
```

Windows 上把 `path` 改为 `D:/Eustia/Video` 即可跨平台使用。

## 状态文件

- `status/todo.json`：待下载番剧（只填**新版 ID**，如 `["3397"]`）
- `status/already.json`：完成记录 `"id:标题"`，**按标题去重**（跨站 ID 不同但标题一致）
- `cache/{aid}_info.json`：剧集解析缓存与已下载集进度

## 已知约束

- `api.xifanacg.com` 有连接级限速：高频请求会被 TLS reset，工具已内置节流（3–5s/次）与退避重试；
- 播放直链有时效（约 30 分钟），工具每集即时签发；
- HLS 线路（action=auto）较慢且需 ffmpeg，未实现；mp4 双线路（AL/xfxf1）足够。
