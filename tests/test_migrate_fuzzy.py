"""迁移模糊匹配单测（离线，不触网）。"""

from xfani_next.migrate import _fuzzy_match, _fuzzy_score


class TestFuzzyScore:
    def test_exact(self):
        assert _fuzzy_score("尼古喵喵", "尼古喵喵") == 1.0

    def test_containment(self):
        # “游戏人生” 包含于旧标题
        assert _fuzzy_score("NO GAME NO LIFE 游戏人生", "游戏人生") >= 0.8

    def test_rename_lowish(self):
        # 译名改写：邻桌→邻座 / 用俄语小声说→轻声地以俄语遮羞
        s = _fuzzy_score(
            "不时用俄语小声说真心话的邻桌艾莉同学",
            "不时轻声地以俄语遮羞的邻座艾莉同学",
        )
        assert 0.5 < s < 0.85

    def test_unrelated(self):
        assert _fuzzy_score("迷宫饭", "胆大党") < 0.58


def _r(aid, title, year=None):
    return {"id": aid, "title": title, "release_year": year}


class TestFuzzyMatch:
    def test_year_disambiguates_sequel(self):
        # 旧“约会大作战”(2013)：第五季(2024) 相似度达标但年份不符，必须排除
        results = [_r(2045, "约会大作战 第五季", 2024), _r(1300, "约会大作战", 2013)]
        hit = _fuzzy_match("约会大作战", results, 2013)
        assert hit is not None and hit["id"] == 1300

    def test_rename_with_year(self):
        results = [_r(2474, "不时轻声地以俄语遮羞的邻座艾莉同学", 2024)]
        hit = _fuzzy_match("不时用俄语小声说真心话的邻桌艾莉同学", results, 2024)
        assert hit is not None and hit["id"] == 2474

    def test_wrong_year_rejected(self):
        results = [_r(2474, "不时轻声地以俄语遮羞的邻座艾莉同学", 2024)]
        assert _fuzzy_match("不时用俄语小声说真心话的邻桌艾莉同学", results, 2014) is None

    def test_no_year_hint_accepts_closest(self):
        results = [_r(1820, "游戏人生", 2014)]
        hit = _fuzzy_match("NO GAME NO LIFE 游戏人生", results, None)
        assert hit is not None and hit["id"] == 1820
