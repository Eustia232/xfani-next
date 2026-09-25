"""旧仓库 already.json（"旧ID:标题"）→ Next ID 映射迁移。

策略：search_animes 按标题搜索 → 精确/规范化标题匹配（含去年份尾）→
命中写入 status/already.json（"新ID:新标题"），未命中写入
status/migrate_unmatched.json 供人工确认。节流由 site.request_with_backoff 统一控制。

refine_unmatched 对未命中项做二次模糊处理：提高 per_page、difflib 相似度、
包含关系，并用年份提示消歧（续作年份不同，可避免误配到续作）。
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path

from . import site, state
from .util import normalize_title, strip_year_tail, title_matches

# 未命中条目的首播年份提示（用于消歧；不匹配宁可留给人工）
YEAR_HINTS = {
    "吹响！悠风号": 2015,
    "东京喰种": 2014,
    "魔法少女小圆": 2011,
    "Code Geass 反叛的鲁路修": 2006,
    "鬼灭之刃": 2019,
    "JOJO的奇妙冒险": 2012,
    "日常": 2011,
    "Re：从零开始的异世界生活": 2016,
    "新石纪": 2019,
    "进击的巨人": 2013,
    "NO GAME NO LIFE 游戏人生": 2014,
    "约会大作战": 2013,
    "不时用俄语小声说真心话的邻桌艾莉同学": 2024,
}


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


def _fuzzy_score(old: str, new: str) -> float:
    """0~1 相似度：全等 1.0；包含关系 ≥0.8；difflib 比率兜底。"""
    a, b = normalize_title(old), normalize_title(new)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    score = SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        score = max(score, 0.8)
    return score


def _fuzzy_match(title: str, results: list[dict], year: int | None) -> dict | None:
    """模糊匹配：命中须满足 (相似度高) 且 (年份与提示一致或无提示)。"""
    best, best_score = None, 0.0
    for a in results:
        ay = a.get("release_year")
        score = _fuzzy_score(title, a.get("title", ""))
        if score < 0.55:
            continue
        if year is not None and ay not in (year, None):
            continue  # 年份不符：宁可放弃也不误配续作
        if score > best_score:
            best, best_score = a, score
    return best


def refine_unmatched(session, threshold_report: float = 0.58) -> None:
    """对 migrate_unmatched.json 做二次模糊处理。

    每条：原词搜索（per_page=12）→ 模糊匹配（年份消歧）→ 仍失败再试
    “{标题} 第一季” 变体 → 全部失败则留在清单。
    """
    path = state.STATUS_DIR / "migrate_unmatched.json"
    if not path.exists():
        print("没有未命中清单，无需处理")
        return
    items = json.loads(path.read_text(encoding="utf-8"))
    print(f"待二次处理 {len(items)} 条…")

    applied, still = [], []
    for i, item in enumerate(items, 1):
        entry = item["entry"]
        title = entry.split(":", 1)[1] if ":" in entry else entry
        year = YEAR_HINTS.get(title)
        hit, how = None, ""
        for attempt, term in enumerate([title, f"{title} 第一季"]):
            try:
                results = site.search_anime(session, term, per_page=12)
            except Exception as exc:  # noqa: BLE001
                print(f"  [{i}/{len(items)}] 搜索失败 {term}: {exc}")
                continue
            hit = _fuzzy_match(title, results, year)
            if hit:
                how = "原词" if attempt == 0 else "加'第一季'变体"
                break
        if hit:
            applied.append((entry, hit["id"], hit["title"], how))
            print(
                f"  [{i}/{len(items)}] ✓ {title} → {hit['id']}《{hit['title']}》"
                f"（{hit.get('release_year')}，{how}）"
            )
        else:
            still.append(item)
            top = max(
                results, key=lambda a: _fuzzy_score(title, a.get("title", "")), default=None
            ) if results else None
            if top:
                print(
                    f"  [{i}/{len(items)}] ✗ 仍不匹配：最接近 {top['id']}《{top['title']}》"
                    f"（{top.get('release_year')}，相似度 "
                    f"{_fuzzy_score(title, top['title']):.2f}）"
                )
            else:
                print(f"  [{i}/{len(items)}] ✗ 仍不匹配：无结果")

    if applied:
        existing = state.load_already()
        for _old, aid, new_title, _how in applied:
            entry = f"{aid}:{new_title}"
            if entry not in existing:
                existing.append(entry)
        state.save_already(existing)
        path.write_text(
            json.dumps(still, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"\n二次处理完成：新增 {len(applied)}，剩余 {len(still)}")
