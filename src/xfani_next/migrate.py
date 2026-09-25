"""旧仓库 already.json（"旧ID:标题"）→ Next ID 映射迁移。

策略：search_animes 按标题搜索 → 精确/规范化标题匹配（含去年份尾）→
命中写入 status/already.json（"新ID:新标题"），未命中写入
status/migrate_unmatched.json 供人工确认。节流由 site.request_with_backoff 统一控制。
"""

from __future__ import annotations

import json
from pathlib import Path

from . import site, state
from .util import normalize_title, strip_year_tail, title_matches


def _match(title: str, results: list[dict]) -> dict | None:
    # 第一轮：常规匹配（全等 / 去年份尾 / 年份一致）
    for a in results:
        if title_matches(title, a.get("title", ""), a.get("release_year")):
            return a
    # 第二轮：双方都去掉年份尾的规范化比对（如 “凉宫春日的忧郁2009” vs “凉宫春日的忧郁”）
    stripped = strip_year_tail(normalize_title(title))
    if not stripped:
        return None
    for a in results:
        nt = normalize_title(a.get("title", ""))
        if nt == stripped or strip_year_tail(nt) == stripped:
            return a
    return None


def run_migrate(session, old_path: Path) -> None:
    if not old_path.exists():
        raise SystemExit(f"找不到旧 already 文件: {old_path}")
    entries = json.loads(old_path.read_text(encoding="utf-8"))
    print(f"旧记录 {len(entries)} 条，开始迁移（每条搜索间隔 3–5s）…")

    matched, unmatched = [], []
    for i, entry in enumerate(entries, 1):
        title = entry.split(":", 1)[1] if ":" in entry else entry
        try:
            results = site.search_anime(session, title, per_page=5)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{len(entries)}] 搜索失败 {title}: {exc}")
            unmatched.append({"entry": entry, "error": str(exc), "candidates": []})
            continue
        hit = _match(title, results)
        if hit:
            matched.append((entry, hit["id"], hit["title"]))
            print(f"  [{i}/{len(entries)}] {title} → {hit['id']}《{hit['title']}》")
        else:
            unmatched.append(
                {
                    "entry": entry,
                    "candidates": [
                        {"id": a["id"], "title": a["title"]} for a in results[:3]
                    ],
                }
            )
            print(f"  [{i}/{len(entries)}] ✗ 未命中: {title}")

    # 命中项合并进 already（新 ID:新标题），保留旧条目做历史
    existing = state.load_already()
    for _old, aid, new_title in matched:
        entry = f"{aid}:{new_title}"
        if entry not in existing:
            existing.append(entry)
    state.save_already(existing)

    unmatched_path = state.STATUS_DIR / "migrate_unmatched.json"
    if unmatched:
        unmatched_path.write_text(
            json.dumps(unmatched, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"\n迁移完成：命中 {len(matched)}，未命中 {len(unmatched)}")
    if unmatched:
        print(f"未命中清单: {unmatched_path}")
