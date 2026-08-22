"""安装体检的回归测试。

体检器的价值全在"可信"上：报假阳性会让人白折腾，
一次报十个问题会让人不知道先修哪个。这两条都要守住。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artemis import doctor as D


def test_checks_run_without_exception():
    steps = D.check_all()
    assert len(steps) >= 5
    for s in steps:
        assert s.status in (D.STATUS_OK, D.STATUS_WARN, D.STATUS_BLOCK)


def test_every_non_ok_step_has_a_reason():
    """只说"缺了什么"没用，必须说"后果是什么" —— 前者不会让人去修。"""
    for s in D.check_all():
        if s.status != D.STATUS_OK:
            assert s.why, f"{s.name} 未说明后果"


def test_render_stops_at_first_blocker(monkeypatch):
    """有多个阻塞项时只指出第一个。一次报十个问题，
    人不知道先修哪个，而且后面的常是第一个的连锁反应。"""
    fake = [
        D.Step("A", D.STATUS_OK, "fine"),
        D.Step("B", D.STATUS_BLOCK, "broken", fix="fix-b", why="因为 B"),
        D.Step("C", D.STATUS_BLOCK, "broken", fix="fix-c", why="因为 C"),
    ]
    txt = D.render(fake)
    assert "下一步：修 B" in txt
    assert "fix-b" in txt
    assert "fix-c" not in txt, "不该同时给出第二个阻塞项的修复命令"
    assert "还有 1 个阻塞项" in txt


def test_render_lists_all_warnings_when_no_blockers():
    """没有阻塞项时反而要把所有降级项列全 —— 这时用户有余裕逐个看。"""
    fake = [
        D.Step("A", D.STATUS_OK, "fine"),
        D.Step("B", D.STATUS_WARN, "w1", fix="fix-b", why="因为 B"),
        D.Step("C", D.STATUS_WARN, "w2", fix="fix-c", why="因为 C"),
    ]
    txt = D.render(fake)
    assert "可以开始用了" in txt
    assert "fix-b" in txt and "fix-c" in txt


def test_render_all_green_gives_usage():
    txt = D.render([D.Step("A", D.STATUS_OK, "fine")])
    assert "全部就绪" in txt
    assert "artemis.lite watch" in txt


def test_fix_commands_use_real_interpreter_path():
    """修复命令要能直接复制粘贴，所以必须用真实解释器路径，
    不能写 'python'（用户的 python 可能指向别的环境）。"""
    for s in D.check_all():
        if s.fix and "pip install" in s.fix:
            assert sys.executable in s.fix


def test_tcp_probe_is_not_used_for_remote_quote_source():
    """回归测试：远程行情源不能用裸 TCP 探测。

    实测中裸 TCP 会给假阳性 —— 代理后面 TCP 能连上（连的是代理），
    但代理拒绝 CONNECT 到目标域名。体检说"网络 OK"然后 AkShare
    神秘失败，用户完全无从下手。
    """
    src = Path(D.__file__).read_text(encoding="utf-8")
    net_block = src[src.index("# ---------- 4. 网络"):src.index("# ---------- 5.")]
    assert "_probe_quote_api" in net_block
    assert "_probe(" not in net_block, "远程行情源不该用裸 TCP 探测"


def test_quote_api_probe_returns_reason_not_just_bool():
    """探测失败要带具体原因，'网络不通'这种结论没法排查。"""
    ok, detail = D._probe_quote_api(timeout=6.0)
    assert isinstance(ok, bool)
    assert detail and len(detail) > 5
    if not ok:
        # 必须包含可据以排查的线索
        assert any(k in detail for k in ("HTTP", "无法请求", "网络错误", "非预期"))


def test_local_probe_still_uses_tcp():
    """本地服务（Ollama 等）用 TCP 探测是合理的：本地端口通了基本就能用，
    而且发真请求会拖慢体检。"""
    assert D._probe("127.0.0.1", 1) is False


def test_main_exit_code_reflects_blockers(monkeypatch):
    monkeypatch.setattr(D, "check_all",
                        lambda **kw: [D.Step("X", D.STATUS_BLOCK, "d", why="w")])
    assert D.main() == 1
    monkeypatch.setattr(D, "check_all",
                        lambda **kw: [D.Step("X", D.STATUS_OK, "d")])
    assert D.main() == 0
