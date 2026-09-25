"""下载器重试/续传单测（FakeSession，离线）。

回归背景：requests 把流式中断包装成 ChunkedEncodingError（不是 ConnectionError），
旧版 except 捕获不到 → 中断不重试（Windows ep2 实际踩坑）。
"""

import http.client
from pathlib import Path

import pytest
import requests

from xfani_next.downloader import download

FULL = b"A" * 1000 + b"B" * 500  # 总长 1500


class FakeResponse:
    def __init__(self, status, chunks, headers=None):
        self.status_code = status
        self._chunks = chunks
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def iter_content(self, chunk_size=1):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FlakySession:
    """第一次读到一半抛 ChunkedEncodingError，第二次按 Range 续传余下分片。"""

    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, stream=True, timeout=None):
        self.calls.append(headers or {})
        if len(self.calls) == 1:
            # 中途断流：先给 700 字节，再抛 requests 包装的中断
            return FakeResponse(200, self._explode())
        rng = headers["Range"]  # bytes=700-
        assert rng == "bytes=700-"
        return FakeResponse(206, [FULL[700:]], headers={"Content-Length": "800"})

    @staticmethod
    def _explode():
        yield FULL[:700]
        raise requests.exceptions.ChunkedEncodingError(
            http.client.IncompleteRead(700, 800)
        )


class TestResumeOnChunkedEncodingError:
    def test_broken_stream_resumes(self, tmp_path: Path):
        dest = tmp_path / "ep.mp4"
        result = download(FlakySession(), "http://x/v.mp4", dest, retries=3)
        assert result == dest
        assert dest.read_bytes() == FULL  # 1000 + 500 拼接完整

    def test_persistent_failure_raises(self, tmp_path: Path):
        class AlwaysBroken:
            def get(self, url, **kw):
                return FakeResponse(200, FlakySession._explode())

        dest = tmp_path / "ep.mp4"
        with pytest.raises(Exception):
            download(AlwaysBroken(), "http://x/v.mp4", dest, retries=1)
        # 失败后 .part 保留（断点数据不丢），正式文件未生成
        assert (tmp_path / "ep.mp4.part").exists()
        assert not dest.exists()
