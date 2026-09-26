"""堆存计费口径：金额计算与计费校验全系统只保留这一份。

列表、详情、登记、生成账单、试算、导出都从这里取金额；算法是纯函数——
Decimal 定点运算、显式 ROUND_HALF_UP 舍入、不读时钟/时区/本地化环境，
本地与部署环境跑出来的必然是同一份结果。要调整口径（比如免费堆存天数）
只改这里，所有入口同时生效。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

CENT = Decimal("0.01")
FREE_STORAGE_DAYS = Decimal("4")  # 免费堆存天数：超过部分才计费


class BillingError(ValueError):
    """计费口径校验失败；message 是可直接展示给页面的中文原因。"""


def _parse_decimal(value: Any, field: str) -> Decimal:
    text = str(value if value is not None else "").strip()
    if not text:
        raise BillingError(f"缺少{field}，无法核算应收金额")
    try:
        return Decimal(text)
    except InvalidOperation:
        raise BillingError(f"{field}「{text}」不是有效数字，无法核算应收金额")


def compute_storage_fee(values: Mapping[str, Any]) -> Decimal:
    """按统一口径核算应收金额：应收 = max(堆存天数 - 免费天数, 0) × 计费标准。

    计费周期缺失、堆存天数为负等情况一律抛 BillingError，由各入口原样展示。
    """
    period = str(values.get("计费周期") or "").strip()
    if not period:
        raise BillingError("缺少计费周期，无法核算应收金额")
    days = _parse_decimal(values.get("堆存天数"), "堆存天数")
    if days < 0:
        raise BillingError(f"堆存天数为负（{days} 天），无法核算应收金额")
    rate = _parse_decimal(values.get("计费标准"), "计费标准")
    if rate < 0:
        raise BillingError(f"计费标准为负（{rate}），无法核算应收金额")
    billable_days = max(days - FREE_STORAGE_DAYS, Decimal("0"))
    return (billable_days * rate).quantize(CENT, rounding=ROUND_HALF_UP)


def format_amount(amount: Decimal) -> str:
    """金额统一落成两位小数字符串，持久化与接口输出都用它，避免浮点走样。"""
    return str(amount.quantize(CENT, rounding=ROUND_HALF_UP))
