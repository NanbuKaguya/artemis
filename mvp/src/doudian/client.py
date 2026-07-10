"""抖店开放平台客户端（P2-半自动上架，AGENTS.md §3）。

⚠️ 合规红线（再强调一次）：写操作**只走这里的官方 API**，严禁 RPA 刷后台。
⚠️ 前置条件（人类完成）：
   1. 在抖店开放平台 (op.jinritemai.com) 创建自研应用，绑定自己店铺
   2. 拿到 app_key/app_secret 放入 .env，完成店铺授权拿到 access_token

已实现（确定性，有测试）：sign() 网关签名、build_draft_payload() 草稿组装。
待实现（TODO 桩）：HTTP call、token 刷新、素材上传。

网关签名算法（以官方文档「签名算法」页为准，实现时逐条核对）：
  1. param_json = 业务参数按 key 升序、无空格、ensure_ascii=False 的 JSON
  2. 拼串: sign_str = app_secret
           + "app_key" + app_key + "method" + method
           + "param_json" + param_json
           + "timestamp" + timestamp + "v" + v
           + app_secret
  3. sign = HMAC-SHA256(key=app_secret, msg=sign_str) 的十六进制小写
     （sign_method 传 "hmac-sha256"）
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

API_GATEWAY = "https://openapi-fxg.jinritemai.com"
API_VERSION = "2"


def canonical_param_json(params: dict) -> str:
    """业务参数 → 规范化 JSON（key 升序、分隔符无空格、保留中文）。"""
    return json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign(app_key: str, app_secret: str, method: str, param_json: str, timestamp: str,
         v: str = API_VERSION) -> str:
    """网关签名（见文件顶部算法说明）。确定性纯函数，测试锚定防回归。"""
    sign_str = (f"{app_secret}app_key{app_key}method{method}"
                f"param_json{param_json}timestamp{timestamp}v{v}{app_secret}")
    return hmac.new(app_secret.encode(), sign_str.encode(), hashlib.sha256).hexdigest()


class DoudianClient:
    def __init__(self):
        self.app_key = os.getenv("DOUDIAN_APP_KEY", "")
        self.app_secret = os.getenv("DOUDIAN_APP_SECRET", "")
        self.access_token = os.getenv("DOUDIAN_ACCESS_TOKEN", "")

    @property
    def available(self) -> bool:
        return bool(self.app_key and self.app_secret and self.access_token)

    def _signed_query(self, method: str, params: dict) -> dict:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        pj = canonical_param_json(params)
        return {
            "app_key": self.app_key, "method": method, "param_json": pj,
            "timestamp": ts, "v": API_VERSION, "sign_method": "hmac-sha256",
            "access_token": self.access_token,
            "sign": sign(self.app_key, self.app_secret, method, pj, ts),
        }

    # ---- TODO(Codex) 按顺序实现 ----

    def call(self, method: str, params: dict) -> dict:
        """TODO(Codex-6): POST {API_GATEWAY}/{method.replace('.', '/')}，
        query 用 self._signed_query(method, params)，body 为 param_json。
        响应 code!=10000 抛 DoudianError(code, msg, sub_msg)。
        失败重试 3 次指数退避；token 过期错误码触发 refresh_token()。"""
        raise NotImplementedError

    def refresh_token(self) -> None:
        """TODO(Codex-7): 调 token.refresh 换新 access_token 并持久化到 .env/秘钥库。"""
        raise NotImplementedError

    def upload_image(self, image_path: str) -> str:
        """TODO(Codex-8): 调 sku.uploadImg / material 系列接口上传主图/详情图，
        返回平台图片 URL（build_draft_payload 的 pic 字段用它）。"""
        raise NotImplementedError

    # ---- 已实现：草稿组装（确定性，可离线测试）----

    def create_product_draft(self, payload: dict) -> dict:
        """创建"未上架"商品草稿。走 product.addV2，**status 必须传 1（下架/草稿态）**，
        发布（status=0 上架）永远由人在后台/闸门确认后触发 —— 这是发布红线。"""
        assert payload.get("status") == 1, "红线：Agent 只能创建草稿态(status=1)，不得直接上架"
        return self.call("product.addV2", payload)


def build_draft_payload(*, category_leaf_id: int, product_title: str,
                        selling_points: list[str], detail_html: str,
                        pic_urls: list[str], sku_list: list[dict],
                        freight_template_id: int = 0) -> dict:
    """把内容工厂产物组装为 product.addV2 参数（草稿态）。

    确定性纯函数：不做任何"补全/编造"，缺参数直接 ValueError（宁缺毋假）。
    sku_list 每项: {"spec": "颜色:红", "price_yuan": 59.9, "stock": 100,
                    "supply_price_yuan": 22.0}
    价格单位：抖店 API 以"分"计 —— 这里集中换算，杜绝散落的 *100。
    """
    if not product_title or not pic_urls or not sku_list:
        raise ValueError("标题/主图/SKU 为必填，缺失即拒绝组装（不编造）")
    if len(product_title) > 60:
        raise ValueError(f"标题超长({len(product_title)}>60)，打回内容工厂重写")

    def yuan_to_fen(y: float) -> int:
        return round(y * 100)

    skus = []
    for s in sku_list:
        price_fen = yuan_to_fen(s["price_yuan"])
        supply_fen = yuan_to_fen(s.get("supply_price_yuan", 0))
        if price_fen <= 0:
            raise ValueError(f"SKU 价格非法: {s}")
        if 0 < price_fen <= supply_fen:
            raise ValueError(f"SKU 售价≤供货价，疑似录入错误: {s}")
        skus.append({"spec_detail": s["spec"], "price": price_fen,
                     "stock_num": int(s["stock"])})

    return {
        "category_leaf_id": category_leaf_id,
        "name": product_title,
        "pic": "|".join(pic_urls),
        "description": detail_html,
        "product_format_new": json.dumps(
            {"卖点": selling_points[:5]}, ensure_ascii=False),
        "spec_prices": skus,
        "freight_id": freight_template_id,
        "reduce_type": 1,          # 库存扣减方式：下单减库存
        "status": 1,               # ★ 草稿/下架态 —— 发布必须过人工闸门
    }
