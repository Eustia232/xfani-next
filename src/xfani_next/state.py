"""状态管理：status/{todo,already,download_config}.json 与 cache/{aid}_info.json。"""

from __future__ import annotations

import json
from pathlib import Path

from .util import normalize_title, title_matches

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_DIR = REPO_ROOT / "status"
CACHE_DIR = REPO_ROOT / "cache"


def _load(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_config() -> dict:
    cfg = _load(STATUS_DIR / "download_config.json", {})
    cfg.setdefault("path", "~/Videos/xfani")
    cfg.setdefault("source_priority", ["AL", "xfxf1"])
    return cfg


def load_todo() -> list[str]:
    return _load(STATUS_DIR / "todo.json", [])


def save_todo(todo: list[str]) -> None:
    _save(STATUS_DIR / "todo.json", todo)


def remove_todo(aid: int) -> None:
    todo = [t for t in load_todo() if str(aid) not in t]
    save_todo(todo)


def load_already() -> list[str]:
    return _load(STATUS_DIR / "already.json", [])


def save_already(entries: list[str]) -> None:
    _save(STATUS_DIR / "already.json", entries)


def is_known_title(title: str) -> bool:
    """按标题去重（already 条目格式 "id:标题"，跨站 ID 不同但标题一致）。"""
    known = [e.split(":", 1)[1] for e in load_already() if ":" in e]
    return any(title_matches(title, k) for k in known)


def add_already(aid: int, title: str) -> None:
    entries = load_already()
    entry = f"{aid}:{title}"
    if entry not in entries:
        entries.append(entry)
        save_already(entries)


def load_cache(aid: int) -> dict:
    return _load(CACHE_DIR / f"{aid}_info.json", {})


def save_cache(aid: int, data: dict) -> None:
    _save(CACHE_DIR / f"{aid}_info.json", data)


def cached_title(aid: int) -> str | None:
    return load_cache(aid).get("title")


def cache_known_titles() -> list[str]:
    """cache 中已解析过的番剧标题（用于去重兜底）。"""
    titles = []
    if CACHE_DIR.exists():
        for p in CACHE_DIR.glob("*_info.json"):
            t = _load(p, {}).get("title")
            if t:
                titles.append(t)
    return titles


def title_in_any_record(title: str) -> bool:
    """标题是否已在 already 或本地缓存中（normalize 后比对）。"""
    nt = normalize_title(title)
    if any(normalize_title(t) == nt for t in cache_known_titles()):
        return True
    return is_known_title(title)
