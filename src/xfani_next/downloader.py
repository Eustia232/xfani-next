"""流式下载：Range 断点续传 + 重试退避。"""

from __future__ import annotations

import http.client
import time
from pathlib import Path

import requests
import urllib3.exceptions
from tqdm import tqdm

CHUNK_SIZE = 256 * 1024


class DownloadError(Exception):
    pass


# 可重试的异常：requests 家族全部（含 ChunkedEncodingError——流式中断时
# requests 会把 urllib3 的 ProtocolError("Connection broken: IncompleteRead…")
# 包装成它抛出，而不是 ConnectionError），以及可能裸抛的底层类型。
RETRYABLE_ERRORS = (
    requests.RequestException,
    urllib3.exceptions.HTTPError,
    http.client.IncompleteRead,
    DownloadError,
)


def download(
    session: requests.Session,
    url: str,
    dest: Path,
    *,
    retries: int = 3,
    resume: bool = True,
) -> Path:
    """下载 url 到 dest，支持断点续传（.part 文件）。

    已知源（moedot/xfvod）对开放 Range 均 206，续传时带 `Range: bytes=N-`。
    完成（大小校验通过或无 Content-Length）后 rename 为正式文件。
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        start = part.stat().st_size if (resume and part.exists()) else 0
        headers = {"Range": f"bytes={start}-"} if start else {}
        try:
            with session.get(url, headers=headers, stream=True, timeout=(15, 60)) as resp:
                if resp.status_code == 416:
                    # 续传区间不满足：多半是已下完但没来得及 rename，直接收尾
                    if part.exists() and part.stat().st_size > 0:
                        part.rename(dest)
                        return dest
                    raise DownloadError(f"416 但无有效 .part: {dest}")
                resp.raise_for_status()

                # 206 = 续传成功；200 = 服务端忽略 Range，从头写
                append = start > 0 and resp.status_code == 206
                if not append:
                    start = 0
                content_length = resp.headers.get("Content-Length")
                total = int(content_length) + start if content_length else None

                mode = "ab" if append else "wb"
                with open(part, mode) as f, tqdm(
                    total=total,
                    initial=start,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=dest.name,
                ) as bar:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            bar.update(len(chunk))

            if total is not None and part.stat().st_size != total:
                raise DownloadError(
                    f"大小不符: {part.stat().st_size} != {total} ({dest})"
                )
            part.rename(dest)
            return dest

        except RETRYABLE_ERRORS as exc:
            last_exc = exc
            if attempt < retries:
                backoff = 2 ** (attempt + 1)
                print(f"\n  下载中断（{exc.__class__.__name__}），{backoff}s 后从断点重试…")
                time.sleep(backoff)

    raise DownloadError(f"下载失败 {url} → {dest}: {last_exc}") from last_exc
