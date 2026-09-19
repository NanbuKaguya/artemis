# sources/ —— L1/L3 原文快照

**证据是快照，不是链接。** URL 会死，页面会被悄悄改版，
证监会的一个 PDF 换个路径，你的"已验证"断言就变成了一句无根据的话
—— 而且你不会收到任何通知。

## 放什么

- L1：法规原文、证监会/交易所公告、上市公司公告、中证指数官方统计
- L3：券商研报 PDF（署名 + 方法论那几页必须在里面）

## 命名

`<机构>-<日期>-<短名>.<ext>`，例如：

```
gov-2024-04-12-guojiutiao.txt
sse-kechuangban-shidangxing.txt
csrc-2025-zhongchangqi-zijin.pdf
```

## 目前有脚本在等的快照

| 文件名 | 取自 | 给哪条断言 |
|---|---|---|
| `gov-2024-04-12-guojiutiao.txt` | gov.cn《关于加强监管防范风险推动资本市场高质量发展的若干意见》 | `inst-69d8655b` |
| `sse-kechuangban-shidangxing.txt` | 上交所 科创板股票交易特别规定 / 投资者适当性管理办法 | `inst-625f832d` |
| `sse-jiaoyi-guize.txt` | 上交所《交易规则》含回转交易那一节 | `inst-623b43f8` |
| `sse-rongzirongquan-xize.txt` | 上交所《融资融券交易实施细则》 | `inst-623b43f8` |

文件名不是硬性的 —— 改了就同步改脚本里的常量和 `kb source` 的 `--src`。

## 用 kb fetch 取

```bash
./kb fetch --list                                   # 还缺哪些
./kb fetch gov-2024-04-12-guojiutiao.txt --url <原址>
./kb fetch sse-jiaoyi-guize.txt --from-file ~/下载/guize.pdf --url <原址>
```

它会抽出纯文本，并把来源另存成 `<快照名>.meta.json`：URL、抓取时间、
**原始字节的 sha256**。sha256 的用处是下次重抓能看出页面变没变 ——
法规被悄悄修订时字节会变，而你不会收到任何通知。

来源信息**不写进快照正文**：快照是 `require_phrases` 搜索的对象，
而 URL 里很可能带着日期（`.../2024-04/12/...`），那正是 `date_variants()`
的候选之一。写进去，快照就给自己作了证。

PDF 需要 `pip install pypdf`。扫描件抽不出文字会直接报错 —— 存下来也没用，
脚本在图片里找不到字。

## ⛔ 这里的每一个字节都必须来自模型之外

不是凭记忆重建，不是"忠实复述"。伪造的原文会通过每一道质量门 ——
来源等级是断言自己声明的、关键短语是写它的人挑的、sha256 是对着伪造文件
算的，全部自洽。然后库会说 verified，而没有任何机制会发现。

所有的门检查的是「来源等级」和「短语命中」，**没有一道在检查
「这份文本是不是真的来自 gov.cn」**。详见 `CLAUDE.md` 的硬闸那一节。

## 纪律

1. 存**全文**，不存摘要。摘要是你的转述，转述就降级成 L4 了。
2. 同时在断言的 `source_ref` 里写上 `sources/<文件名>`，
   `kb source <id> --src sources/<文件名>`。
3. 纯文本优先。验证脚本靠 `require_phrases()` 在里面找关键短语，
   扫描版 PDF 找不到字。PDF 就同时存一份 `.txt`。
4. 原文变了（法规修订）→ 存新快照 + `kb falsify` 旧断言 + `kb lead` 新断言。
   **不要原地覆盖快照。** 覆盖了，被打脸的那条断言就失去了它当初的依据，
   墓碑上的教训也就没法复核了。
