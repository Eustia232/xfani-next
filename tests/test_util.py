"""util 模块单测。"""

from xfani_next.util import normalize_title, sanitize_filename, title_matches


class TestSanitizeFilename:
    def test_replaces_slash(self):
        assert sanitize_filename("Re：从零开始/异世界") == "Re：从零开始-异世界"

    def test_removes_illegal(self):
        assert sanitize_filename('a<b>c:d"e|f?g*h') == "a-b-c-d-e-f-g-h"

    def test_keeps_chinese_and_parens(self):
        assert sanitize_filename("尼古喵喵第12集(临时版)") == "尼古喵喵第12集(临时版)"

    def test_strips_dots(self):
        assert sanitize_filename("name...") == "name"

    def test_empty(self):
        assert sanitize_filename("") == "unnamed"


class TestNormalizeTitle:
    def test_strips_space_and_punct(self):
        assert normalize_title("凉宫春日的忧郁 2009") == "凉宫春日的忧郁2009"

    def test_fullwidth_to_halfwidth(self):
        assert normalize_title("ＢＡＮＧ ＤＲＥＡＭ！") == "bangdream"

    def test_case_fold(self):
        assert normalize_title("BanG Dream!") == normalize_title("bang dream")


class TestTitleMatches:
    def test_exact(self):
        assert title_matches("尼古喵喵", "尼古喵喵")

    def test_punct_insensitive(self):
        assert title_matches("狂赌之渊 ××", "狂赌之渊××")

    def test_year_tail(self):
        assert title_matches("凉宫春日的忧郁 2009", "凉宫春日的忧郁")

    def test_year_via_release_year(self):
        assert title_matches("凉宫春日的忧郁 2009", "凉宫春日的忧郁", new_year=2009)

    def test_different_titles(self):
        assert not title_matches("迷宫饭", "胆大党")

    def test_season_suffix_must_match(self):
        assert not title_matches("碧蓝之海", "碧蓝之海 第二季")
