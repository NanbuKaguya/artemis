# verify/ —— 一条断言一个脚本

`verified` 状态**只能由脚本挣到**。没有人工 `--manual`、没有 `--attest`、
没有"我读过原文了"。这是刻意的：人工确认是这套系统唯一可能的后门，
一旦留着，三个月后库里就会堆满谁也说不清凭什么的 verified 条目。

## 退出码契约

状态变更需要**退出码 + stdout 上的结论行**同时满足：

| 退出码 | stdout 行首 | `kb verify` 的动作 |
|---|---|---|
| `0` | `HOLDS:` | `status=verified`，`last_verified=今天` |
| `1` | `FALSIFIED:` | `status=falsified`，自动写 `ledger/falsified/<id>.md` |
| 其他 / 缺结论行 | — | **不确定**：状态不变 |

为什么不能只看退出码：**Python 脚本抛未捕获异常时退出码就是 1**。
只认退出码的话，一个写错的脚本会被读成"断言被数据打脸"，
库会自动写一块墓碑、记下一条根本不存在的教训。
用 `kv.holds()` / `kv.falsified()` 就自动带上结论行。

第三档是重点。"跑失败了"不等于"断言错了"，把两者混在一起，
库就会在你没注意的时候开始撒谎。

同一次输出里既有 `HOLDS:` 又有 `FALSIFIED:` 也判为不确定 ——
自相矛盾的脚本不是证据。

## 运行环境

- 工作目录 = 库根目录
- `KB_ROOT`、`KB_CLAIM_ID` 两个环境变量
- `verify/` 在 `PYTHONPATH` 上，所以 `import kbverify` 直接可用
- 超时 300 秒

## 两种典型形态

**L1 / L3（制度层、研报）—— 核对原文快照**

```python
import kbverify as kv
kv.require_phrases(
    "gov-2024-04-12-guojiutiao.txt",
    "关于加强监管防范风险推动资本市场高质量发展的若干意见",
    kv.date_variants(2024, 4, 12),      # 候选组：任一命中即可
    ("1+N", "1＋N"),
)
```

**候选组（tuple）放宽的是写法，不是事实。** 正文用阿拉伯数字、落款用中文数字、
网页版和 PDF 版不一致 —— 这些都不该算验证失败。`date_variants()` 直接生成
一个日期的常见写法。少一个**成分**照样不通过。

匹配前会先 `normalize()`：去掉全部空白（PDF 转文本会把 "50万元" 拆到两行）、
全角转半角。它只消除同一字符串的不同写法，**不做同义替换、不做繁简转换** ——
一旦 normalize 开始消除"不同的说法"，验证就比断言宽松了。

**数字边界是硬的**：短语 `"50万元"` 不会在 `"150万元"` 里命中。门槛从 50 万
改成 150 万之后，朴素的子串匹配会让脚本继续说 HOLDS，库里就留下一条过时的
verified —— 往 verified 那个方向错，比漏验证危险得多。

一条断言依赖多份原文时（比如 T+1 要《交易规则》，融券要《融资融券交易实施细则》）：

```python
kv.require_across({
    "sse-jiaoyi-guize.txt":        ("当日不得卖出", "回转交易"),
    "sse-rongzirongquan-xize.txt": ("融券卖出", "买券还券"),
})
```

全部命中才 HOLDS；任何一份缺失或任何一条落空都是不确定。

快照缺失时它退 2（不确定）而不是退 0。URL 会死、页面会被悄悄改，
`sources/` 下的本地快照不会 —— 所以证据是快照，不是链接。

**短语找不到时它也退 2，不退 1。** 匹配不上绝大多数时候是口径问题而不是
事实问题：原文可能写"二〇二四年四月十二日"、PDF 转文本可能把数字拆开、
页面可能只是换了个说法。判成 falsified 的话，库会自动写一块记录着
不存在的教训的墓碑 —— 就是上面那个失败模式换了个入口。
制度层断言的 falsify 由人来做：读到修订后的法规，手动 `kb falsify`。

**L2（结构层）—— 自己算一遍**

```python
import kbverify as kv
median, index_ret = compute_quarter(...)
if median >= index_ret:
    kv.falsified(f"中位数 {median:.2%} >= 指数 {index_ret:.2%}")
kv.holds(f"中位数 {median:.2%} < 指数 {index_ret:.2%}")
```

## 写脚本时的纪律

1. 把 `statement` 和 `if_wrong` 原样抄进脚本顶部。改断言就必须改脚本。
2. 脚本检验的是 `if_wrong`，不是 `statement`。你要找的是反例。
3. 数据源接不上就退 2。**永远不要**为了让脚本跑通而放宽判定条件。
