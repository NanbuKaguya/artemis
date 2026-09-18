"""ashare-kb 的测试，重点全在质量门上。

这套系统的价值等于它的门有多严。门漏了，库就只是个笔记堆，
而且是一个看起来很权威的笔记堆 —— 比没有更糟。
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent   # sys.path 见 conftest.py

from kb_cli import db, ledger  # noqa: E402
from kb_cli.__main__ import main  # noqa: E402
from kb_cli.ids import claim_id  # noqa: E402

import kbverify as kv  # noqa: E402

TODAY = _dt.date.today().isoformat()


@pytest.fixture()
def kb(tmp_path, monkeypatch):
    monkeypatch.setenv("ASHARE_KB_ROOT", str(tmp_path))
    db.init(tmp_path)
    return tmp_path


def run(*argv) -> int:
    return main(list(argv))


def conn_of(root) -> sqlite3.Connection:
    return db.connect(root)


def base_row(**over) -> dict:
    row = dict(
        id="inst-test0001",
        statement="某条断言",
        layer="institutional",
        if_wrong="某个观测",
        source_tier=1,
        source_ref="sources/x.txt",
        status="lead",
        verify_script=None,
        last_verified=None,
        created_at=TODAY,
        stale_after_days=None,
    )
    row.update(over)
    return row


def insert(conn, row):
    cols = list(row)
    conn.execute(
        f"INSERT INTO claim ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        [row[c] for c in cols],
    )
    conn.commit()


def write_script(root, name, body) -> str:
    p = root / "verify" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return f"verify/{name}"


# ---------------------------------------------------------------------------
# 质量门：L4/L5 永远不能是 verified
# ---------------------------------------------------------------------------

def test_l5_cannot_be_inserted_as_verified(kb):
    with pytest.raises(sqlite3.IntegrityError, match="L4/L5"):
        insert(conn_of(kb), base_row(
            source_tier=5, status="verified",
            last_verified=TODAY, verify_script="verify/x.py"))


def test_l4_cannot_be_updated_to_verified(kb):
    """设计稿点名的那条：写入时是 lead，事后 UPDATE 成 verified 就绕过了门。"""
    conn = conn_of(kb)
    insert(conn, base_row(source_tier=4, status="lead"))
    with pytest.raises(sqlite3.IntegrityError, match="L4/L5"):
        conn.execute(
            "UPDATE claim SET status='verified', last_verified=?, "
            "verify_script='verify/x.py' WHERE id=?", (TODAY, "inst-test0001"))


def test_tier_cannot_be_raised_on_a_verified_claim(kb):
    """反向绕行：先以 L2 挣到 verified，再把 tier 改成 L5。"""
    conn = conn_of(kb)
    insert(conn, base_row(source_tier=2, status="verified",
                          last_verified=TODAY, verify_script="verify/x.py"))
    with pytest.raises(sqlite3.IntegrityError, match="L4/L5"):
        conn.execute("UPDATE claim SET source_tier=5 WHERE id=?", ("inst-test0001",))


# ---------------------------------------------------------------------------
# 空字节绕行：NOT NULL 挡不住 ''
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("col", ["statement", "if_wrong", "source_ref"])
@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_blank_strings_are_not_values(kb, col, blank):
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn_of(kb), base_row(**{col: blank}))


def test_if_wrong_cannot_be_blanked_by_update(kb):
    conn = conn_of(kb)
    insert(conn, base_row())
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE claim SET if_wrong='' WHERE id=?", ("inst-test0001",))


# ---------------------------------------------------------------------------
# verified 的完整性：没有日期就永远抓不到，没有脚本就是人工后门
# ---------------------------------------------------------------------------

def test_verified_requires_last_verified(kb):
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn_of(kb), base_row(status="verified", last_verified=None,
                                     verify_script="verify/x.py"))


def test_verified_requires_verify_script(kb):
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn_of(kb), base_row(status="verified", last_verified=TODAY,
                                     verify_script=None))


def test_verified_requires_nonblank_verify_script(kb):
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn_of(kb), base_row(status="verified", last_verified=TODAY,
                                     verify_script="  "))


def test_state_layer_is_rejected(kb):
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn_of(kb), base_row(layer="state"))


# ---------------------------------------------------------------------------
# lead
# ---------------------------------------------------------------------------

def test_lead_is_always_lead(kb):
    assert run("lead", "个人投资者占成交量七成", "--layer", "structural",
               "--tier", "1", "--src", "sources/a.txt",
               "--if-wrong", "年鉴口径不符") == 0
    row = conn_of(kb).execute("SELECT * FROM claim").fetchone()
    assert row["status"] == "lead"
    assert row["last_verified"] is None


def test_same_statement_is_the_same_claim(kb):
    args = ("lead", "重复的断言", "--layer", "structural", "--tier", "2",
            "--src", "s", "--if-wrong", "w")
    assert run(*args) == 0
    assert run(*args) == 1  # 主键撞车，不是第二条记录
    assert conn_of(kb).execute("SELECT count(*) FROM claim").fetchone()[0] == 1


def test_stale_defaults_by_layer(kb):
    run("lead", "制度断言", "--layer", "institutional", "--tier", "1",
        "--src", "s", "--if-wrong", "w")
    run("lead", "结构断言", "--layer", "structural", "--tier", "2",
        "--src", "s", "--if-wrong", "w")
    rows = dict(conn_of(kb).execute("SELECT layer, stale_after_days FROM claim"))
    assert rows["institutional"] is None
    assert rows["structural"] == 90


def test_stale_after_never(kb):
    run("lead", "已封闭的历史测算", "--layer", "structural", "--tier", "2",
        "--src", "s", "--if-wrong", "w", "--stale-after", "never")
    assert conn_of(kb).execute(
        "SELECT stale_after_days FROM claim").fetchone()[0] is None


# ---------------------------------------------------------------------------
# verify：退出码契约
# ---------------------------------------------------------------------------

HOLDS = "import sys; print('HOLDS: ok'); sys.exit(0)"
FALSE = "import sys; print('FALSIFIED: 反例: 中位数 > 指数'); sys.exit(1)"
BROKEN = "import sys; print('INCONCLUSIVE: 数据源没接上'); sys.exit(2)"
CRASH = "raise RuntimeError('boom')"                       # 未捕获异常 -> 退出码 1
SILENT_OK = "import sys; sys.exit(0)"                      # 忘了声明结论
SILENT_FAIL = "import sys; sys.exit(1)"                    # 与崩溃无法区分
CONTRADICTORY = "print('HOLDS: a'); print('FALSIFIED: b')"


def seed_one(kb, tier=2, layer="structural"):
    run("lead", "可验证的断言", "--layer", layer, "--tier", str(tier),
        "--src", "sources/a.txt", "--if-wrong", "反例出现")
    return claim_id(layer, "可验证的断言")


def test_rc0_verifies(kb):
    cid = seed_one(kb)
    script = write_script(kb, f"{cid}.py", HOLDS)
    assert run("verify", cid, "--script", script) == 0
    row = conn_of(kb).execute("SELECT * FROM claim WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "verified"
    assert row["last_verified"] == TODAY


def test_rc1_falsifies_and_writes_tombstone(kb):
    cid = seed_one(kb)
    script = write_script(kb, f"{cid}.py", FALSE)
    assert run("verify", cid, "--script", script) == 1
    row = conn_of(kb).execute("SELECT status FROM claim WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "falsified"
    tomb = kb / "ledger" / "falsified" / f"{cid}.md"
    assert tomb.exists()
    body = tomb.read_text(encoding="utf-8")
    assert "反例: 中位数 > 指数" in body   # 证据进了墓碑
    assert "## 教训" in body


@pytest.mark.parametrize("body", [BROKEN, CRASH, SILENT_OK, SILENT_FAIL, CONTRADICTORY])
def test_other_rc_changes_nothing(kb, body):
    """脚本坏了 ≠ 断言错了。两者混在一起，库就开始撒谎。

    SILENT_OK：脚本跑完没声明结论就退 0 —— 不能算 verified。
    SILENT_FAIL / CRASH：Python 未捕获异常退出码也是 1 —— 不能算 falsified，
    否则一个写错的脚本会让库自动写墓碑、记下一条根本不存在的教训。
    """
    cid = seed_one(kb)
    script = write_script(kb, f"{cid}.py", body)
    assert run("verify", cid, "--script", script) == 2
    row = conn_of(kb).execute("SELECT status FROM claim WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "lead"


def test_a_crashing_script_never_writes_a_tombstone(kb):
    cid = seed_one(kb)
    run("verify", cid, "--script", write_script(kb, f"{cid}.py", CRASH))
    assert not (kb / "ledger" / "falsified" / f"{cid}.md").exists()


def test_script_binding_survives_an_inconclusive_run(kb):
    cid = seed_one(kb)
    script = write_script(kb, f"{cid}.py", BROKEN)
    run("verify", cid, "--script", script)
    row = conn_of(kb).execute("SELECT verify_script FROM claim WHERE id=?", (cid,)).fetchone()
    assert row["verify_script"] == script


def test_verify_without_script_refuses(kb):
    cid = seed_one(kb)
    assert run("verify", cid) == 1  # KBError -> 1
    assert conn_of(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "lead"


def test_verify_refuses_l4_before_backtracking(kb):
    cid = seed_one(kb, tier=4)
    script = write_script(kb, f"{cid}.py", HOLDS)
    assert run("verify", cid, "--script", script) == 1
    assert conn_of(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "lead"


def test_script_outside_verify_is_refused(kb):
    """脚本路径不能逃出 verify/ —— 否则 verify 就成了任意命令执行。"""
    cid = seed_one(kb)
    outside = kb / "evil.py"
    outside.write_text(HOLDS, encoding="utf-8")
    assert run("verify", cid, "--script", "../evil.py") == 1
    assert run("verify", cid, "--script", "evil.py") == 1
    assert conn_of(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "lead"


# ---------------------------------------------------------------------------
# kbverify：L1 快照核对
# ---------------------------------------------------------------------------

SNAPSHOT_SCRIPT = (
    "import kbverify as kv\n"
    "kv.require_phrases('yuanwen.txt', '2024年4月12日', '1+N')\n"
)


def install_kbverify(root):
    """验证脚本靠 PYTHONPATH 上的 verify/ 拿到 kbverify。"""
    (root / "verify").mkdir(parents=True, exist_ok=True)
    (root / "verify" / "kbverify.py").write_text(
        (ROOT / "verify" / "kbverify.py").read_text("utf-8"), encoding="utf-8")


def snapshot(root, text, name="yuanwen.txt"):
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "sources" / name).write_text(text, encoding="utf-8")


def setup_snapshot_claim(kb, text=None):
    install_kbverify(kb)
    if text is not None:
        snapshot(kb, text)
    cid = seed_one(kb, tier=1, layer="institutional")
    return cid, write_script(kb, f"{cid}.py", SNAPSHOT_SCRIPT)


def test_snapshot_with_all_phrases_verifies(kb):
    cid, script = setup_snapshot_claim(kb, "……2024年4月12日国务院印发……形成1+N政策体系……")
    assert run("verify", cid, "--script", script) == 0
    assert conn_of(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "verified"


def test_missing_phrase_is_inconclusive_never_falsified(kb):
    """短语匹配不上几乎总是口径问题，不是事实问题。

    原文可能写"二〇二四年四月十二日"、PDF 转文本可能把数字拆开。
    判成 falsified 的话，库会自动写一块记录着不存在的教训的墓碑。
    """
    cid, script = setup_snapshot_claim(kb, "……二〇二四年四月十二日国务院印发……1+N……")
    assert run("verify", cid, "--script", script) == 2
    assert conn_of(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "lead"
    assert not (kb / "ledger" / "falsified" / f"{cid}.md").exists()


def test_missing_snapshot_is_inconclusive(kb):
    cid, script = setup_snapshot_claim(kb)  # 不建快照
    assert run("verify", cid, "--script", script) == 2
    assert conn_of(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "lead"


# ---------------------------------------------------------------------------
# source：回溯
# ---------------------------------------------------------------------------

def test_backtracking_l4_to_l1_then_verify(kb):
    cid = seed_one(kb, tier=4)
    script = write_script(kb, f"{cid}.py", HOLDS)
    assert run("source", cid, "--tier", "1", "--src", "sources/yuanwen.txt") == 0
    assert run("verify", cid, "--script", script) == 0
    assert conn_of(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "verified"


def test_changing_source_resets_verification(kb):
    """来源换了，之前那次验证就不再算数。"""
    cid = seed_one(kb)
    write_script(kb, f"{cid}.py", HOLDS)
    run("verify", cid, "--script", f"verify/{cid}.py")
    assert run("source", cid, "--src", "sources/别的来源.txt") == 0
    row = conn_of(kb).execute("SELECT * FROM claim WHERE id=?", (cid,)).fetchone()
    assert row["status"] == "lead"
    assert row["last_verified"] is None


def test_source_without_changes_is_an_error(kb):
    assert run("source", seed_one(kb)) == 1


# ---------------------------------------------------------------------------
# stale：淘汰机制
# ---------------------------------------------------------------------------

def age(conn, cid, days):
    old = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    conn.execute("UPDATE claim SET last_verified=? WHERE id=?", (old, cid))
    conn.commit()


def make_verified(kb, layer="structural", tier=2, stale_after=None):
    stmt = f"断言-{layer}-{stale_after}"
    argv = ["lead", stmt, "--layer", layer, "--tier", str(tier),
            "--src", "sources/a.txt", "--if-wrong", "w"]
    if stale_after is not None:
        argv += ["--stale-after", stale_after]
    run(*argv)
    cid = claim_id(layer, stmt)
    write_script(kb, f"{cid}.py", HOLDS)
    run("verify", cid, "--script", f"verify/{cid}.py")
    return cid


def test_structural_demoted_after_90_days(kb):
    cid = make_verified(kb)
    conn = conn_of(kb)
    age(conn, cid, 91)
    assert run("stale") == 0
    assert db.connect(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "stale"


def test_structural_not_demoted_at_90_days(kb):
    cid = make_verified(kb)
    age(conn_of(kb), cid, 90)
    run("stale")
    assert db.connect(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "verified"


def test_institutional_never_goes_stale(kb):
    """制度不会自己变。它变的时候你手动 falsify。"""
    cid = make_verified(kb, layer="institutional", tier=1)
    age(conn_of(kb), cid, 4000)
    run("stale")
    assert db.connect(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "verified"


def test_closed_historical_measurement_never_goes_stale(kb):
    """已封闭区间的测算不会腐烂。误报会训练你忽略 kb stale，那就毁了淘汰机制。"""
    cid = make_verified(kb, stale_after="never")
    age(conn_of(kb), cid, 4000)
    run("stale")
    assert db.connect(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "verified"


def test_stale_dry_run_does_not_write(kb):
    cid = make_verified(kb)
    age(conn_of(kb), cid, 200)
    assert run("stale", "--dry-run") == 0
    assert db.connect(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "verified"


def test_leads_never_go_stale(kb):
    """lead 放了一年也只是没验证，不是过期。"""
    cid = seed_one(kb)
    conn = conn_of(kb)
    conn.execute("UPDATE claim SET created_at='2020-01-01' WHERE id=?", (cid,))
    conn.commit()
    run("stale")
    assert db.connect(kb).execute(
        "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "lead"


# ---------------------------------------------------------------------------
# falsify / 账本 / 重建
# ---------------------------------------------------------------------------

def test_falsified_claims_are_kept_not_deleted(kb):
    cid = seed_one(kb)
    assert run("falsify", cid, "--why", "制度在2026年改了") == 0
    row = conn_of(kb).execute("SELECT * FROM claim WHERE id=?", (cid,)).fetchone()
    assert row is not None and row["status"] == "falsified"
    assert "制度在2026年改了" in (kb / "ledger" / "falsified" / f"{cid}.md").read_text("utf-8")


def test_ledger_is_append_only_across_a_claim_lifecycle(kb):
    cid = seed_one(kb)
    write_script(kb, f"{cid}.py", HOLDS)
    run("verify", cid, "--script", f"verify/{cid}.py")
    run("falsify", cid, "--why", "后来被打脸")
    actions = [e["action"] for e in ledger.history(kb, cid)]
    assert actions == ["lead", "bind", "verify", "falsify"]


def test_rebuild_from_ledger_reproduces_the_db(kb):
    cid = seed_one(kb)
    write_script(kb, f"{cid}.py", HOLDS)
    run("verify", cid, "--script", f"verify/{cid}.py")
    before = dict(conn_of(kb).execute("SELECT * FROM claim WHERE id=?", (cid,)).fetchone())

    assert run("rebuild", "--force") == 0
    after = dict(db.connect(kb).execute("SELECT * FROM claim WHERE id=?", (cid,)).fetchone())
    assert before == after


def test_rebuild_refuses_to_clobber_without_force(kb):
    assert run("rebuild") == 1


def test_ledger_rows_are_readable_json(kb):
    seed_one(kb)
    line = ledger.events_path(kb).read_text("utf-8").splitlines()[0]
    event = json.loads(line)
    assert event["action"] == "lead"
    assert event["row"]["status"] == "lead"
    assert "可验证的断言" in line  # 不转义成 \uXXXX，账本要人能读


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------

def test_digest_leads_with_the_contract(kb):
    seed_one(kb)
    assert run("digest") == 0
    text = (kb / "digest" / "latest.md").read_text("utf-8")
    assert "以库为准，你是错的那个" in text
    assert "L4/L5" in text
    head = text.split("## verified 断言")[0]
    assert "操作契约" in head  # 契约必须在证据前面


def test_digest_says_so_when_nothing_is_verified(kb):
    seed_one(kb)
    run("digest")
    text = (kb / "digest" / "latest.md").read_text("utf-8")
    assert "一条都没有" in text
    assert "不要把它们当作事实使用" in text


# ---------------------------------------------------------------------------
# digest 自动刷新：循环的终点不能靠人记得
# ---------------------------------------------------------------------------

def digest_text(root) -> str:
    return (root / "digest" / "latest.md").read_text("utf-8")


def test_lead_refreshes_the_digest_without_kb_digest(kb):
    run("lead", "新记的线索", "--layer", "structural", "--tier", "2",
        "--src", "s", "--if-wrong", "w")
    assert "新记的线索" in digest_text(kb)


def test_verify_refreshes_the_digest(kb):
    cid = seed_one(kb)
    write_script(kb, f"{cid}.py", HOLDS)
    run("verify", cid, "--script", f"verify/{cid}.py")
    text = digest_text(kb)
    assert "verified **1**" in text
    assert "一条都没有" not in text     # 旧的"还没挣到任何东西"必须消失


def test_falsify_refreshes_the_digest(kb):
    cid = seed_one(kb)
    run("falsify", cid, "--why", "后来被打脸")
    assert "falsified 1" in digest_text(kb)


def test_stale_refreshes_the_digest(kb):
    cid = make_verified(kb)
    age(conn_of(kb), cid, 200)
    run("stale")
    assert "stale 1" in digest_text(kb)


def test_readonly_commands_do_not_touch_the_digest(kb):
    cid = seed_one(kb)
    run("digest")
    before = (kb / "digest" / "latest.md").stat().st_mtime_ns
    run("list")
    run("show", cid)
    run("stale")          # 没有到期的，不写库
    assert (kb / "digest" / "latest.md").stat().st_mtime_ns == before


# ---------------------------------------------------------------------------
# kb doctor：门还拦不拦得住
# ---------------------------------------------------------------------------

def test_doctor_passes_on_a_healthy_kb(kb):
    seed_one(kb)
    assert run("doctor", "--offline") == 0


def test_doctor_fails_when_the_update_gate_is_dropped(kb):
    """光检查触发器在不在是在度量"组件在不在"。这里要的是它真的拦。"""
    conn = conn_of(kb)
    conn.execute("DROP TRIGGER no_weak_verified_update")
    conn.commit()
    assert run("doctor", "--offline") == 1


def test_doctor_fails_when_the_insert_gate_is_dropped(kb):
    conn = conn_of(kb)
    conn.execute("DROP TRIGGER no_weak_verified_insert")
    conn.commit()
    assert run("doctor", "--offline") == 1


def test_doctor_probes_leave_nothing_behind(kb):
    """探针是真写进去的，必须全部回滚 —— 一条都不许留在库里或账本里。"""
    seed_one(kb)
    before = conn_of(kb).execute("SELECT count(*) FROM claim").fetchone()[0]
    ledger_before = ledger.events_path(kb).read_text("utf-8")
    run("doctor", "--offline")
    assert conn_of(kb).execute("SELECT count(*) FROM claim").fetchone()[0] == before
    assert conn_of(kb).execute(
        "SELECT count(*) FROM claim WHERE id LIKE '%doctor%'").fetchone()[0] == 0
    assert ledger.events_path(kb).read_text("utf-8") == ledger_before


def test_doctor_warns_when_the_digest_lags(kb, capsys):
    seed_one(kb)
    run("digest")
    (kb / "digest" / "latest.md").write_text("# 过期的 digest\n", encoding="utf-8")
    assert run("doctor", "--offline") == 0      # 落后是警告，不是失败
    assert "落后于库" in capsys.readouterr().out


def test_doctor_on_a_missing_kb_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("ASHARE_KB_ROOT", str(tmp_path))
    assert run("doctor", "--offline") == 1


# ---------------------------------------------------------------------------
# kbverify：排版差异不该算验证失败，但数字边界必须干净
# ---------------------------------------------------------------------------

def test_normalize_folds_layout_not_meaning():
    """PDF 换行、全角编码都不是内容差异。"""
    assert kv.normalize("50 万\n元") == "50万元"
    assert kv.normalize("（２０个交易日）") == "(20个交易日)"
    assert kv.normalize("不\t低\r\n于") == "不低于"


def test_normalize_does_not_fold_different_wordings():
    """normalize 只能消除同一字符串的不同写法。它一旦开始消除不同的说法，
    验证就比断言宽松了。"""
    assert kv.normalize("五十万元") != kv.normalize("50万元")
    assert kv.normalize("二十个交易日") != kv.normalize("20个交易日")


@pytest.mark.parametrize("text,phrase,expected", [
    ("不低于人民币50万元", "50万元", True),
    ("不低于人民币150万元", "50万元", False),   # 门槛改成150万，不能还说 HOLDS
    ("不低于人民币500万元", "50万元", False),
    ("参与证券交易满24个月", "24个月", True),
    ("参与证券交易满124个月", "24个月", False),
    ("前20个交易日", "20个交易日", True),
    ("前120个交易日", "20个交易日", False),
    ("融券卖出", "融券卖出", True),             # 非数字短语不受边界规则影响
])
def test_digit_boundaries(text, phrase, expected):
    """往 verified 方向错比漏验证危险得多。"""
    assert kv.contains(text, phrase) is expected


def test_date_variants_covers_the_chinese_numeral_form():
    v = kv.date_variants(2024, 4, 12)
    assert "2024年4月12日" in v
    assert "二〇二四年四月十二日" in v
    assert "2024-04-12" in v


@pytest.mark.parametrize("n,cn", [(1, "一"), (10, "十"), (12, "十二"),
                                  (20, "二十"), (24, "二十四"), (31, "三十一")])
def test_cn_num(n, cn):
    assert kv._cn_num(n) == cn


# ---------------------------------------------------------------------------
# 候选组与多份快照
# ---------------------------------------------------------------------------

ALT_SCRIPT = (
    "import kbverify as kv\n"
    "kv.require_phrases('yuanwen.txt', kv.date_variants(2024, 4, 12), ('1+N', '1＋N'))\n"
)


def test_chinese_numeral_date_still_verifies(kb):
    """原来押注会失败的那一幕：正文写中文数字日期。候选组把它接住了。"""
    install_kbverify(kb)
    snapshot(kb, "……二〇二四年四月十二日印发……“1+N”政策体系……")
    cid = seed_one(kb, tier=1, layer="institutional")
    assert run("verify", cid, "--script", write_script(kb, f"{cid}.py", ALT_SCRIPT)) == 0


def test_a_genuinely_absent_phrase_is_still_inconclusive(kb):
    """候选组放宽的是写法，不是事实。少一个成分照样不算通过。"""
    install_kbverify(kb)
    snapshot(kb, "……二〇二四年四月十二日印发……")   # 没有 1+N
    cid = seed_one(kb, tier=1, layer="institutional")
    assert run("verify", cid, "--script", write_script(kb, f"{cid}.py", ALT_SCRIPT)) == 2


ACROSS_SCRIPT = (
    "import kbverify as kv\n"
    "kv.require_across({'a.txt': ('当日不得卖出',), 'b.txt': ('买券还券',)})\n"
)


def setup_across(kb, **files):
    install_kbverify(kb)
    for name, text in files.items():
        snapshot(kb, text, name=f"{name}.txt")
    cid = seed_one(kb, tier=1, layer="institutional")
    return cid, write_script(kb, f"{cid}.py", ACROSS_SCRIPT)


def test_require_across_needs_every_snapshot(kb):
    cid, script = setup_across(kb, a="当日买入的证券，当日不得卖出")  # 缺 b
    assert run("verify", cid, "--script", script) == 2


def test_require_across_needs_every_phrase(kb):
    cid, script = setup_across(kb, a="当日买入的证券，当日不得卖出", b="融券卖出")
    assert run("verify", cid, "--script", script) == 2   # b 里没有"买券还券"


def test_require_across_holds_when_all_present(kb):
    cid, script = setup_across(kb, a="当日买入的证券，当日不得卖出",
                               b="融券卖出后可以买券还券")
    assert run("verify", cid, "--script", script) == 0


def test_the_three_institutional_scripts_are_bound_and_inconclusive(kb):
    """仓库里那三个脚本在没有快照时必须退 2 —— 一条都不许自己变成 verified。"""
    install_kbverify(kb)
    for name in ("inst-69d8655b", "inst-625f832d", "inst-623b43f8"):
        src = (ROOT / "verify" / f"{name}.py").read_text("utf-8")
        cid = seed_one(kb, tier=1, layer="institutional")
        rc = run("verify", cid, "--script", write_script(kb, f"{cid}.py", src))
        assert rc == 2, f"{name} 在没有快照时没有退 2"
        assert conn_of(kb).execute(
            "SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0] == "lead"
        conn_of(kb).execute("DELETE FROM claim WHERE id=?", (cid,))
        conn_of(kb).commit()
