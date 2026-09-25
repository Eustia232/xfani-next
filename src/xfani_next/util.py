"""通用工具：文件名清洗、标题规范化匹配。"""

import re
import unicodedata

# 需要从文件名中去除的字符（Windows/Linux 通吃）
_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f\\/]')
# 标题规范化时去除的标点/符号（含全角）
_PUNCT = re.compile(
    r"[\s（）()\[\]【】《》<>:：·.。,，、;；!！?？~～\-—_=+*&#@%^\"'`｜|]+"
)
_YEAR_TAIL = re.compile(r"(\d{4})$")


def sanitize_filename(name: str) -> str:
    """清洗文件名：非法字符替换为 '-'，去掉首尾空白与点。"""
    cleaned = _ILLEGAL.sub("-", name).strip().rstrip(".")
    return cleaned or "unnamed"


def normalize_title(title: str) -> str:
    """标题规范化：全角转半角、去空白与标点、转小写。"""
    text = unicodedata.normalize("NFKC", title)
    return _PUNCT.sub("", text).lower()


def strip_year_tail(normalized: str) -> str:
    """去掉规范化标题末尾的 4 位年份（旧站标题常带 '凉宫春日的忧郁2009'）。"""
    return _YEAR_TAIL.sub("", normalized)


def title_matches(old_title: str, new_title: str, new_year: int | None = None) -> bool:
    """判断旧站标题与新站标题是否指向同一部番。

    匹配策略（依次尝试）：
    1. 规范化后全等；
    2. 去掉旧标题末尾年份后全等（如 “凉宫春日的忧郁2009” → “凉宫春日的忧郁”）；
    3. 互为去掉年份尾的前缀相等。
    """
    a = normalize_title(old_title)
    b = normalize_title(new_title)
    if not a or not b:
        return False
    if a == b:
        return True
    a2, b2 = strip_year_tail(a), strip_year_tail(b)
    if a2 == b2:
        return True
    if new_year is not None and str(new_year) in (a, a2):
        # 旧标题带年份且与新站年份一致，去掉年份后再比
        return a2 == b2 or a == b2
    return False
