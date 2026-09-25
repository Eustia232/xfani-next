"""site 模块解析与选源单测（全部离线 fixture）。"""

import json
from pathlib import Path

import pytest

from xfani_next.site import SiteError, parse_anime_page, pick_candidate

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def anime_html() -> str:
    return (FIXTURES / "anime_3397.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def playback_data() -> dict:
    return json.loads((FIXTURES / "playback_121222.json").read_text(encoding="utf-8"))


class TestParseAnimePage:
    def test_aid(self, anime_html):
        assert parse_anime_page(anime_html).aid == 3397

    def test_title(self, anime_html):
        assert parse_anime_page(anime_html).title == "尼古喵喵"

    def test_episode_count(self, anime_html):
        assert len(parse_anime_page(anime_html).episodes) == 12

    def test_first_episode(self, anime_html):
        ep = parse_anime_page(anime_html).episodes[0]
        assert ep.episode_id == 121222
        assert "第01集" in ep.label

    def test_episode_ids_deduped(self, anime_html):
        ids = [e.episode_id for e in parse_anime_page(anime_html).episodes]
        assert len(ids) == len(set(ids))

    def test_no_episodes_raises(self):
        with pytest.raises(SiteError):
            parse_anime_page("<html><body>empty</body></html>")


class TestPickCandidate:
    def test_prefers_al_by_default(self, playback_data):
        candidates = playback_data["candidates"]
        url, code = pick_candidate(candidates)
        assert code == "AL"
        assert "xfvod.pro" in url

    def test_priority_override(self, playback_data):
        url, code = pick_candidate(playback_data["candidates"], ["xfxf1", "AL"])
        assert code == "xfxf1"
        assert "moedot.net" in url

    def test_fallback_first_when_priority_missed(self, playback_data):
        url, code = pick_candidate(playback_data["candidates"], ["NOT_EXIST"])
        assert code in {"xfxf1", "AL", "CS"}

    def test_no_candidates_raises(self):
        with pytest.raises(SiteError):
            pick_candidate([])
