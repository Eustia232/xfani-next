"""状态加载容错单测（离线）。"""

import json

from xfani_next.state import _loads_tolerant


class TestLoadsTolerant:
    def test_normal_json(self):
        assert _loads_tolerant('{"path": "D:/Eustia/Video"}') == {"path": "D:/Eustia/Video"}

    def test_windows_single_backslash(self):
        # Windows 手写路径：\E \V 是 JSON 非法转义，应自动修复
        raw = '{\n    "path": "D:\\Eustia\\Video"\n}'.replace("\\\\", "\\")
        data = _loads_tolerant(raw)
        assert data["path"] == "D:\\Eustia\\Video"

    def test_keeps_legal_escapes(self):
        raw = '{"note": "a\\nb\\u4e2d\\/c"}'
        data = _loads_tolerant(raw)
        assert data["note"] == "a\nb中/c"

    def test_keeps_escaped_backslash(self):
        raw = '{"path": "D:\\\\Eustia\\\\Video"}'
        data = _loads_tolerant(raw)
        assert data["path"] == "D:\\Eustia\\Video"

    def test_todo_list(self):
        assert _loads_tolerant('["3397"]') == ["3397"]
