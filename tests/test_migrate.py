"""迁移匹配逻辑单测（离线 fixture）。"""

import json
from pathlib import Path

from xfani_next.migrate import _match

FIXTURES = Path(__file__).parent / "fixtures"


def _results() -> list[dict]:
    return json.loads((FIXTURES / "search_尼古喵喵.json").read_text(encoding="utf-8"))


class TestMatch:
    def test_exact_title(self):
        hit = _match("尼古喵喵", _results())
        assert hit is not None and hit["id"] == 3397

    def test_no_match(self):
        assert _match("完全不相关的名字", _results()) is None
