"""Agent 调用层的回归测试。

重点不是功能正确，而是**契约稳定**：agent 依赖退出码和 JSON 结构做分支，
这两样一旦漂移，agent 会静默做错事而不是报错。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artemis.service import (
    EXIT_BADARGS, EXIT_FAIL, EXIT_OK, EXIT_SKIP, EXIT_STALE,
    COMMANDS, Envelope, _parse, main,
)


def run(argv: list[str], cwd: Path | None = None) -> tuple[int, dict]:
    """跑一次命令，返回 (退出码, 解析后的 JSON)。"""
    p = subprocess.run(
        [sys.executable, "-m", "artemis.service", *argv],
        capture_output=True, text=True,
        cwd=str(cwd) if cwd else str(Path(__file__).resolve().parents[1]),
    )
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"输出不是合法 JSON。stdout={p.stdout[:300]} stderr={p.stderr[:300]}")


# ---------------------------------------------------------------- 输出契约
@pytest.mark.parametrize("cmd", ["health", "session", "review", "help"])
def test_every_command_emits_valid_json(cmd):
    """agent 会无条件 json.loads()。任何命令吐非 JSON 都是致命的。"""
    _, out = run([cmd])
    assert isinstance(out, dict)
    assert "ok" in out and "command" in out and "generated_at" in out


def test_unknown_command_is_structured_not_crash():
    code, out = run(["definitely-not-a-command"])
    assert code == EXIT_BADARGS
    assert out["ok"] is False
    assert "available" in out["data"], "应告知有哪些可用命令，方便 agent 自纠"


def test_exception_returns_structured_error_not_traceback(monkeypatch):
    """顶层必须兜住异常。让 agent 看到 traceback 等于让它什么都做不了。"""
    def boom(_args):
        raise RuntimeError("模拟内部错误")
    monkeypatch.setitem(COMMANDS, "health", boom)
    code = main(["health"])
    assert code == EXIT_FAIL


# ---------------------------------------------------------------- 退出码
def test_non_trading_day_exits_skip_not_fail():
    """非交易日是 skip(3) 不是 fail(1)。

    这个区分很重要：agent 把 skip 当故障会天天误告警，
    把 fail 当 skip 会漏掉真故障。
    """
    code, out = run(["session"])
    assert code in (EXIT_OK, EXIT_SKIP)
    if out["data"]["recommended_action"] == "skip":
        assert code == EXIT_SKIP


def test_bad_args_exit_code():
    code, out = run(["journal-add", "--code", "600519"])
    assert code == EXIT_BADARGS
    assert "缺少必填字段" in out["error"]


def test_screen_without_codes_is_bad_args():
    code, out = run(["screen"])
    assert code == EXIT_BADARGS


# ---------------------------------------------------------------- 参数解析
def test_parse_key_value():
    cmd, args = _parse(["screen", "--codes", "600519,000001", "--adv20"])
    assert cmd == "screen"
    assert args["codes"] == ["600519", "000001"]
    assert args["adv20"] is True


def test_parse_json_blob():
    """agent 传一坨 JSON 是最省事的方式，必须支持。"""
    cmd, args = _parse(["journal-add", "--json", '{"code":"600519","side":"buy"}'])
    assert cmd == "journal-add"
    assert args["code"] == "600519"


def test_parse_dashes_normalized_to_underscore():
    _, args = _parse(["x", "--holding-days", "30"])
    assert args["holding_days"] == "30"


# ---------------------------------------------------------------- 健康检查
def test_health_reports_timezone_mismatch():
    """服务器跑 UTC 而代码假设北京时间，是最隐蔽的部署故障。

    health 必须同时报出两个时间，让人一眼看出偏差。
    """
    _, out = run(["health"])
    d = out["data"]
    assert "now_cn" in d and "now_local" in d
    assert "+08:00" in d["now_cn"], "北京时间必须带 +08:00 偏移"


def test_health_never_echoes_secrets():
    """只报凭证是否存在，绝不回显值。"""
    _, out = run(["health"])
    blob = json.dumps(out, ensure_ascii=False)
    assert "anthropic_key_present" in blob
    assert "sk-ant" not in blob


def test_health_reports_calendar_state():
    _, out = run(["health"])
    cal = out["data"]["calendar"]
    assert "is_trading_day" in cal and "basis" in cal
    # 没有日历缓存时必须明说，不能假装知道节假日
    if cal["calendar_source"] == "none":
        assert "fallback" in cal["basis"]


# ---------------------------------------------------------------- 日志写入
def test_journal_add_rejects_weak_thesis(tmp_path):
    """事前承诺不合格是 bad_args 不是 fail —— 这不是系统故障，
    是"这笔交易不该做"，agent 应该把它转达给人。"""
    code, out = run(["journal-add", "--json", json.dumps({
        "code": "600519", "side": "buy", "size_pct": "0.05",
        "source": "discretionary", "thesis": "短", "invalidation": "",
        "journal_path": str(tmp_path / "j.jsonl"),
    })])
    assert code == EXIT_BADARGS
    assert out["error_type"] == "validation"
    assert len(out["data"]["issues"]) >= 2


def test_journal_add_accepts_complete_intent(tmp_path):
    jp = tmp_path / "j.jsonl"
    code, out = run(["journal-add", "--json", json.dumps({
        "code": "600519", "side": "buy", "size_pct": "0.05", "source": "system",
        "thesis": "动量与低波双高，且已通过排雷检查",
        "invalidation": "跌破 20 日均线或触发 12% 止损",
        "journal_path": str(jp),
    })])
    assert code == EXIT_OK, out
    assert jp.exists()
    rec = json.loads(jp.read_text(encoding="utf-8").splitlines()[0])
    assert rec["code"] == "600519" and rec["source"] == "system"


def test_preflight_without_data_is_fail_not_crash():
    code, out = run(["preflight", "--data-dir", "/nonexistent/path/xyz"])
    assert code == EXIT_FAIL
    assert out["error_type"] == "no_data"
