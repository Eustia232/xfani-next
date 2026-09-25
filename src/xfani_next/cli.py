"""命令行入口。

用法示例：
    uv run xfani --search 胆大党          # 按名字查新版 ID
    uv run xfani --list 3397             # 仅解析剧集列表预览
    uv run xfani --id 3397               # 下载整部
    uv run xfani --id 3397 --ep 1-3      # 下载指定范围
    uv run xfani                         # 处理 status/todo.json 队列
    uv run xfani --migrate               # 旧 already 标题 → 新 ID 映射
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import site, state
from .downloader import download
from .migrate import run_migrate
from .util import sanitize_filename, title_matches


def parse_ep_spec(spec: str | None, total: int) -> list[int]:
    """把 "1,5,7-9" 这类描述解析为 1-based 序号列表；None 返回全部。"""
    if not spec:
        return list(range(1, total + 1))
    picked: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            picked.update(range(int(a), int(b) + 1))
        elif part:
            picked.add(int(part))
    return sorted(i for i in picked if 1 <= i <= total)


def resolve_aid(args) -> int:
    target = getattr(args, "target", None)
    if target:
        if target.isdigit():
            return int(target)
        import re

        m = re.search(r"/anime/(\d+)", target)
        if m:
            return int(m.group(1))
        raise SystemExit(f"无法从目标解析番剧 ID: {target}")
    if args.id:
        return int(args.id)
    if args.url:
        import re

        m = re.search(r"/anime/(\d+)", args.url)
        if not m:
            raise SystemExit(f"无法从 URL 解析番剧 ID: {args.url}")
        return int(m.group(1))
    raise SystemExit("需要 --id 或 --url（或留空处理 todo 队列）")


def get_info(session, aid: int) -> site.AnimeInfo:
    cache = state.load_cache(aid)
    if cache.get("episodes"):
        return site.AnimeInfo(
            aid=aid,
            title=cache["title"],
            episodes=[site.Episode(**e) for e in cache["episodes"]],
        )
    info = site.get_anime(session, aid)
    state.save_cache(
        aid,
        {
            "title": info.title,
            "episodes": [
                {"episode_id": e.episode_id, "label": e.label} for e in info.episodes
            ],
            "done": [],
        },
    )
    return info


def download_anime(session, aid: int, *, ep_spec=None, source_priority=None) -> bool:
    """下载一部番。返回是否全部完成（已存在的也算完成）。"""
    cfg = state.load_config()
    priority = source_priority or cfg["source_priority"]
    base = Path(cfg["path"]).expanduser()

    info = get_info(session, aid)
    title = info.title
    print(f"《{title}》aid={aid}，共 {len(info.episodes)} 集")

    if state.title_in_any_record(title):
        print(f"  《{title}》已在 already 记录中，跳过")
        state.remove_todo(aid)
        return True

    dest_dir = base / sanitize_filename(title)
    cache = state.load_cache(aid)
    done: list[str] = list(cache.get("done", []))

    positions = parse_ep_spec(ep_spec, len(info.episodes))
    pending: list[site.Episode] = []
    for pos in positions:
        ep = info.episodes[pos - 1]
        dest = dest_dir / sanitize_filename(f"{title}{ep.label}") .with_suffix(".mp4")
        if str(ep.episode_id) in done:
            continue
        if dest.exists() and dest.stat().st_size > 1024 * 1024:
            done.append(str(ep.episode_id))
            print(f"  已存在，跳过: {dest.name}")
            continue
        pending.append((ep, dest))

    failures = []
    for ep, dest in pending:
        try:
            url, code = site.resolve_episode(session, ep.episode_id, priority)
            print(f"  {ep.label} ← [{code}] {url[:80]}…")
            download(session, url, dest)
            done.append(str(ep.episode_id))
            cache["done"] = done
            state.save_cache(aid, cache)
        except Exception as exc:  # noqa: BLE001 单集失败不阻塞整部
            print(f"  ✗ {ep.label} 失败: {exc}")
            failures.append(ep.label)

    cache["done"] = done
    state.save_cache(aid, cache)

    all_done = not failures and len(done) >= len(info.episodes)
    if all_done:
        state.add_already(aid, title)
        state.remove_todo(aid)
        print(f"  ✔ 《{title}》全部完成，已写入 already")
    else:
        print(f"  未完成: 失败 {failures or '无'}，完成 {len(done)}/{len(info.episodes)}")
    return all_done


def cmd_search(session, term: str) -> None:
    results = site.search_anime(session, term, per_page=8)
    if not results:
        print(f"没有搜到 “{term}”")
        return
    print(f"共 {results[0].get('total_count', len(results))} 条结果：")
    for a in results:
        print(
            f"  id={a['id']:<6} {a['title']}（{a.get('release_year')}，"
            f"{a.get('current_episodes')}/{a.get('total_episodes')}集）"
            f" 原名: {a.get('title_original') or '-'}"
        )


def cmd_list(session, aid: int) -> None:
    info = get_info(session, aid)
    print(f"《{info.title}》aid={aid}，共 {len(info.episodes)} 集：")
    for i, ep in enumerate(info.episodes, start=1):
        print(f"  {i:>2}. {ep.label}  (episode_id={ep.episode_id})")


def run_todo(session, **kwargs) -> None:
    todo = state.load_todo()
    if not todo:
        print("todo 队列为空（status/todo.json）")
        return
    for item in list(todo):
        print(f"处理 todo: {item}")
        import re

        m = re.search(r"/anime/(\d+)", item)
        aid = int(m.group(1)) if m else int(item)
        download_anime(session, aid, **kwargs)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="xfani", description="稀饭动漫 Next 站下载器")
    parser.add_argument("target", nargs="?", help="番剧 ID 或 URL（可选，如 3397）")
    parser.add_argument("--url", help="番剧页 URL，如 https://next.xifanacg.com/anime/3397")
    parser.add_argument("--id", help="新版番剧 ID，如 3397")
    parser.add_argument("--search", help="按标题搜索新版 ID")
    parser.add_argument("--list", action="store_true", help="仅解析剧集列表预览")
    parser.add_argument("--ep", help="集数范围，如 1-3 或 1,5,7-9")
    parser.add_argument("--source", help="线路优先级，逗号分隔，如 AL,xfxf1")
    parser.add_argument("--migrate", action="store_true", help="旧 already 标题 → 新 ID 映射")
    parser.add_argument("--old", default=str(Path.home() / "Codes/xfani/status/already.json"),
                        help="旧仓库 already.json 路径（--migrate 用）")
    args = parser.parse_args(argv)

    session = site.make_session()
    try:
        if args.migrate:
            run_migrate(session, Path(args.old).expanduser())
            return
        if args.search:
            cmd_search(session, args.search)
            return
        if args.list:
            cmd_list(session, resolve_aid(args))
            return
        if args.target or args.url or args.id:
            download_anime(
                session,
                resolve_aid(args),
                ep_spec=args.ep,
                source_priority=args.source.split(",") if args.source else None,
            )
            return
        run_todo(
            session,
            ep_spec=args.ep,
            source_priority=args.source.split(",") if args.source else None,
        )
    except KeyboardInterrupt:
        print("\n用户中断")
        sys.exit(130)


if __name__ == "__main__":
    main()
