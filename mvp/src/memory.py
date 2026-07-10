"""Memory / 权重校准 —— 系统"越用越准"的护城河（蓝图 4.4）。

MVP 用本地 JSON 落盘；生产替换为向量库 + 特征库 + 结构化经验库。
提供：实盘成败回填、评分权重的贝叶斯式增量校准。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .scoring import DEFAULT_WEIGHTS

_STORE = Path(os.getenv("MEMORY_PATH", Path(__file__).resolve().parent.parent / "data" / "memory.json"))


def _load() -> dict:
    if _STORE.exists():
        return json.loads(_STORE.read_text(encoding="utf-8"))
    return {"weights": dict(DEFAULT_WEIGHTS), "outcomes": [], "winning_features": []}


def _save(mem: dict) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def get_weights() -> dict:
    return _load().get("weights", dict(DEFAULT_WEIGHTS))


def record_outcome(spu_id: str, dims: dict, success: bool, roi: float | None = None) -> None:
    """回填一个品的实盘成败标签，并沉淀成功特征。"""
    mem = _load()
    mem["outcomes"].append({"spu_id": spu_id, "dims": dims, "success": success, "roi": roi})
    if success:
        # 记录成功品的强维度（>0.7）作为"爆品特征"
        strong = [k for k, v in dims.items() if v >= 0.7]
        mem["winning_features"].append({"spu_id": spu_id, "strong_dims": strong})
    _save(mem)


def calibrate_weights(lr: float = 0.05) -> dict:
    """基于实盘成败，向"能区分成败的维度"倾斜权重（简化梯度校准）。

    思路：某维度在成功品上均值 − 在失败品上均值 = 该维度的"判别力"。
    判别力越高的维度，权重上调；最后归一化保证 Σw=1。
    """
    mem = _load()
    outcomes = mem["outcomes"]
    if len(outcomes) < 10:   # 样本太少不校准，避免过拟合噪声
        return mem["weights"]

    wins = [o["dims"] for o in outcomes if o["success"]]
    losses = [o["dims"] for o in outcomes if not o["success"]]
    if not wins or not losses:
        return mem["weights"]

    def mean(rows, k):
        return sum(r.get(k, 0) for r in rows) / len(rows)

    w = dict(mem["weights"])
    for k in w:
        discriminative = mean(wins, k) - mean(losses, k)   # 可正可负
        w[k] = max(0.01, w[k] + lr * discriminative)
    # 归一化
    s = sum(w.values())
    w = {k: round(v / s, 4) for k, v in w.items()}
    mem["weights"] = w
    _save(mem)
    return w
