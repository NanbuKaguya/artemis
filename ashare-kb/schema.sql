-- ashare-kb schema
--
-- 设计约束（不是风格问题，是命门）：
--   1. 没有 state 层。成交额/两融/估值分位/当前风格不进库。
--   2. 每条断言必须可证伪 —— if_wrong 不能为空。
--   3. L4/L5 来源永远不能支撑 verified。INSERT 和 UPDATE 两条路都要堵。
--   4. 空字符串不是"有值"。NOT NULL 只挡 NULL，挡不住 ''，
--      这就是 "gates guard the namespace, writes bypass via bytes"。
--      注意 SQLite 的 trim(X) 默认只去空格 —— 单参数版本挡不住 '\n\t'，
--      所以下面一律显式给出字符集。

PRAGMA foreign_keys = ON;

-- 空白字符集：空格/制表/换行/回车。SQLite 的 trim(X) 只去空格。

CREATE TABLE IF NOT EXISTS claim (
  id            TEXT PRIMARY KEY,

  -- 一句话，必须可证伪。
  -- 不许带换行：这是把"一句话"从注释变成约束。一条断言的正文里若能塞进
  -- 换行，它就能在 digest 里伪造出整节"已验证断言" —— 而 digest 是下一个
  -- 会话唯一会读的东西。渲染那一步也会压成单行，这里是第二道。
  statement     TEXT NOT NULL
                CHECK(length(trim(statement, ' ' || char(9) || char(10) || char(13))) > 0)
                CHECK(instr(statement, char(10)) = 0 AND instr(statement, char(13)) = 0),

  -- 只有两层。state 层被 CHECK 挡在库外。
  layer         TEXT NOT NULL CHECK(layer IN ('institutional','structural')),

  -- 什么观测推翻它。空 = 不可证伪 = 不是断言。
  if_wrong      TEXT NOT NULL CHECK(length(trim(if_wrong, ' ' || char(9) || char(10) || char(13))) > 0),

  source_tier   INTEGER NOT NULL CHECK(source_tier BETWEEN 1 AND 5),
  source_ref    TEXT NOT NULL CHECK(length(trim(source_ref, ' ' || char(9) || char(10) || char(13))) > 0),

  status        TEXT NOT NULL CHECK(status IN ('lead','verified','falsified','stale')),

  -- verify/ 下的脚本。没有脚本就不可能 verified（见下方 CHECK）。
  verify_script TEXT,

  last_verified DATE,
  created_at    DATE NOT NULL,

  -- verified 时脚本读过的快照及其 sha256（JSON）。
  -- 作用是让 kb doctor 能发现"验的时候是这份原文，现在不是了" ——
  -- 法规被悄悄修订时字节会变，而没有任何人会通知你。
  evidence      TEXT,

  -- 衰减周期（天）。NULL = 不衰减。
  -- institutional 默认 NULL（制度不会自己变，变了你手动 falsify）。
  -- structural   默认 90。
  -- 已封闭的历史测算（"2026H1 中位数 -14.99%"）应显式设 NULL：
  -- 它不会腐烂，误报会训练你忽略 kb stale，那就毁掉了淘汰机制本身。
  stale_after_days INTEGER CHECK(stale_after_days IS NULL OR stale_after_days > 0),

  -- verified 必须带验证日期，否则 kb stale 永远抓不到它
  CHECK (status <> 'verified' OR last_verified IS NOT NULL),

  -- verified 必须有验证脚本。人工"我读过了"是这套系统唯一的后门，焊死。
  CHECK (status <> 'verified' OR (verify_script IS NOT NULL
         AND length(trim(verify_script, ' ' || char(9) || char(10) || char(13))) > 0))
);

CREATE INDEX IF NOT EXISTS claim_status_idx ON claim(status);
CREATE INDEX IF NOT EXISTS claim_layer_idx  ON claim(layer);

-- 质量门：L4/L5 不得为 verified —— INSERT 路
CREATE TRIGGER IF NOT EXISTS no_weak_verified_insert
BEFORE INSERT ON claim
WHEN NEW.status = 'verified' AND NEW.source_tier >= 4
BEGIN
  SELECT RAISE(ABORT, 'L4/L5 cannot be verified: backtrack to an L1-L3 source first (kb source <id> --tier N --src ...)');
END;

-- 质量门：UPDATE 路。少了这条，整个分级形同虚设：
-- 先以 lead 写入 L5，再 UPDATE 成 verified，门就绕过去了。
-- 同一条 WHEN 也覆盖"把 tier 改高但状态留在 verified"这种反向绕行。
CREATE TRIGGER IF NOT EXISTS no_weak_verified_update
BEFORE UPDATE ON claim
WHEN NEW.status = 'verified' AND NEW.source_tier >= 4
BEGIN
  SELECT RAISE(ABORT, 'L4/L5 cannot be verified: backtrack to an L1-L3 source first (kb source <id> --tier N --src ...)');
END;
