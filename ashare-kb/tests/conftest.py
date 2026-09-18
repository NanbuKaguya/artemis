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


import pytest  # noqa: E402

from kb_cli import db  # noqa: E402


@pytest.fixture()
def kb(tmp_path, monkeypatch):
    """一个空库，根目录指向 tmp_path。

    放在 conftest 里而不是某个测试文件里 —— 多个文件都要用，
    留在一个文件里就会变成跨文件的隐式依赖，只在单独跑时才暴露。
    """
    monkeypatch.setenv("ASHARE_KB_ROOT", str(tmp_path))
    db.init(tmp_path)
    return tmp_path
