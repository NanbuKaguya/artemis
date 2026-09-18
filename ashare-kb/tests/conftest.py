"""测试的 sys.path 设置。

放在这里而不是各个测试文件里：否则单独跑 pytest tests/test_kb.py 会挂，
而全量跑时又会被别的文件的 sys.path 副作用掩盖过去 —— 一个只在
"单独跑某个文件"时出现的失败，正是最容易被忽略的那种。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for path in (ROOT, ROOT / "verify"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
