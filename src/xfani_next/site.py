"""Next 站访问层：页面解析、播放直链签发、搜索 RPC。

所有对 api.xifanacg.com 的请求都经过节流（网关对高频新建连接会 TLS reset），
并带指数退避重试。
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

NEXT_BASE = "https://next.xifanacg.com"
API_BASE = "https://api.xifanacg.com"
PLAYBACK_API = f"{API_BASE}/functions/v1/issue-web-playback"
SEARCH_RPC = f"{API_BASE}/rest/v1/rpc/search_animes"
# 站点前端自带的 public key（公开信息，用于匿名调用 Supabase REST RPC）
PUBLISHABLE_KEY = "sb_publishable_OBIVAWACIX6lPXrO98_z24_HcsmalkA"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 两次 API 调用之间的最小间隔（秒），实际在 min~max 间随机
THROTTLE_MIN, THROTTLE_MAX = 3.0, 5.0

_playback_url_re = re.compile(r"/play/(\d+)")
_title_paren_re = re.compile(r"\s*\(\d{4}\)\s*")
_ep_label_re = re.compile(r"第\s*\d+\s*集")


@dataclass
class Episode:
    episode_id: int
    label: str  # 如 “第01集”


@dataclass
class AnimeInfo:
    aid: int
    title: str
    episodes: list[Episode] = field(default_factory=list)


class SiteError(Exception):
    pass


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": UA,
            "Referer": f"{NEXT_BASE}/",
            "Accept": "*/*",
        }
    )
    return session


_last_call = 0.0


def _throttle() -> None:
    """API 调用节流：距上次调用至少 THROTTLE_MIN~MAX 秒。"""
    global _last_call
    wait = random.uniform(THROTTLE_MIN, THROTTLE_MAX) - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def request_with_backoff(
    session: requests.Session,
    method: str,
    url: str,
    *,
    retries: int = 3,
    api: bool = False,
    **kwargs,
) -> requests.Response:
    """带退避的请求。api=True 表示走 api.xifanacg.com，先节流。

    网关对高频连接会直接 TLS reset（ConnectionError），按 2^n 秒退避重试。
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        if api:
            _throttle()
        try:
            resp = session.request(method, url, timeout=(15, 60), **kwargs)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("retry-after", "30") or 30)
                print(f"  限速触发，等待 {retry_after}s 后重试…")
                time.sleep(retry_after)
                last_exc = SiteError("rate_limited")
                continue
            return resp
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt < retries:
                backoff = 2 ** (attempt + 1)
                print(f"  连接失败（{exc.__class__.__name__}），{backoff}s 后重试…")
                time.sleep(backoff)
    raise SiteError(f"请求失败 {url}: {last_exc}") from last_exc


def parse_anime_page(html: str) -> AnimeInfo:
    """解析番剧页 SSR HTML，得到 aid、标题与剧集列表。"""
    soup = BeautifulSoup(html, "html.parser")

    aid = 0
    seen: dict[int, Episode] = {}
    order: list[int] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = _playback_url_re.search(href)
        if not m:
            continue
        eid = int(m.group(1))
        label = "".join(a.get_text(" ", strip=True).split()) or f"第{eid}集"
        if eid not in seen:
            seen[eid] = Episode(episode_id=eid, label=label)
            order.append(eid)
        elif _ep_label_re.search(label) and not _ep_label_re.search(seen[eid].label):
            # 顶部“立即观看”等按钮先出现时会占用标签；剧集列表的 “第NN集” 更可信
            seen[eid] = Episode(episode_id=eid, label=label)
        if not aid:
            am = re.search(r"/anime/(\d+)", href)
            if am:
                aid = int(am.group(1))

    if not order:
        raise SiteError("页面中未找到剧集链接")

    title = ""
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)
    if not title and soup.title and soup.title.string:
        title = soup.title.string.split("·")[0].strip()
    title = _title_paren_re.sub("", title).strip()

    if not aid:
        raise SiteError("页面中未找到番剧 ID")
    if not title:
        raise SiteError("页面中未找到标题")

    return AnimeInfo(aid=aid, title=title, episodes=[seen[i] for i in order])


def get_anime(session: requests.Session, aid: int) -> AnimeInfo:
    resp = request_with_backoff(session, "GET", f"{NEXT_BASE}/anime/{aid}")
    resp.raise_for_status()
    return parse_anime_page(resp.text)


def pick_candidate(
    candidates: list[dict], source_priority: list[str] | None = None
) -> tuple[str, str]:
    """从候选直链中按优先级选出 (url, source_code)。纯函数，便于单测。"""
    priority = list(source_priority or ["AL", "xfxf1"])
    by_code = {c.get("source_code"): c for c in candidates if c.get("url")}
    for code in priority:
        if code in by_code:
            return by_code[code]["url"], code
    if candidates:
        first = candidates[0]
        return first["url"], first.get("source_code", "?")
    raise SiteError("没有可用候选源")


def resolve_episode(
    session: requests.Session,
    episode_id: int,
    source_priority: list[str] | None = None,
) -> tuple[str, str]:
    """签发某集播放直链，按 source 优先级返回 (url, source_code)。

    调用 issue-web-playback(action=fallback) 拿全部候选 mp4 直链。
    """
    resp = request_with_backoff(
        session,
        "POST",
        PLAYBACK_API,
        api=True,
        json={"action": "fallback", "episode_id": episode_id},
    )
    data = resp.json()
    if not data.get("ok"):
        raise SiteError(f"issue-web-playback 失败: {data.get('error')} (episode {episode_id})")
    return pick_candidate(data.get("candidates") or [], source_priority)


def search_anime(session: requests.Session, term: str, per_page: int = 5) -> list[dict]:
    """按标题搜索番剧（Supabase RPC，匿名 public key）。"""
    resp = request_with_backoff(
        session,
        "POST",
        SEARCH_RPC,
        api=True,
        json={"search_term": term, "page_number": 1, "items_per_page": per_page},
        headers={
            "apikey": PUBLISHABLE_KEY,
            "Authorization": f"Bearer {PUBLISHABLE_KEY}",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []
