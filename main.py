"""兼容入口：保持 `python main.py` 的使用习惯（等价于 `uv run xfani`）。"""

from xfani_next.cli import main

if __name__ == "__main__":
    main()
