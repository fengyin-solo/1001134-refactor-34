"""堆存计费共用口径：金额只在这里算一次，列表、详情、登记、动作、导出、汇总都走它。

设计约定：
- 金额用 Decimal 计算、ROUND_HALF_UP 保留两位，最终以字符串（如 "12.50"）返回，
  不依赖浮点、时区、地区设置，本地与部署环境跑出同一份结果。
- 不可计费的原因文案集中在本文件的常量里，各入口只引用、不各自编写。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# 不可计费原因（统一口径，各入口共用同一份文案）
REASON_PERIOD_MISSING = "计费周期缺失"
REASON_DAYS_MISSING = "堆存天数缺失"
REASON_DAYS_INVALID = "堆存天数不是有效数字"
REASON_DAYS_NEGATIVE = "堆存天数为负"
REASON_RATE_MISSING = "计费标准缺失"
REASON_RATE_INVALID = "计费标准不是有效数字"
REASON_RATE_NEGATIVE = "计费标准为负"

NOTE_BILLABLE = "可计费"

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class BillingDecision:
    """一次计费判断的结果：能不能计费、金额是多少、不能计费时原因是什么。"""

    ok: bool
    amount: str | None
    reasons: tuple[str, ...]


def parse_decimal(value: Any) -> Decimal | None:
    """把页面或接口传来的数值统一解析成 Decimal；解析不了返回 None。

    浮点先过 str 再进 Decimal，避免 0.1 这类二进制误差混进金额。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, (int, float, str)):
        text = str(value).strip()
        if not text:
            return None
        try:
            number = Decimal(text)
        except InvalidOperation:
            return None
    else:
        return None
    if not number.is_finite():
        return None
    return number


def format_amount(number: Decimal) -> str:
    """金额统一保留两位小数、四舍五入到分，输出纯数字字符串。"""
    return str(number.quantize(_CENT, rounding=ROUND_HALF_UP))


def evaluate_billing(row: dict[str, Any]) -> BillingDecision:
    """对一条计费单数据做计费判断：缺周期、天数为负等原因在这里统一给出。"""
    reasons: list[str] = []

    period = str(row.get("计费周期") or "").strip()
    if not period:
        reasons.append(REASON_PERIOD_MISSING)

    days_raw = row.get("堆存天数")
    if days_raw is None or str(days_raw).strip() == "":
        reasons.append(REASON_DAYS_MISSING)
        days = None
    else:
        days = parse_decimal(days_raw)
        if days is None:
            reasons.append(REASON_DAYS_INVALID)
        elif days < 0:
            reasons.append(REASON_DAYS_NEGATIVE)

    rate_raw = row.get("计费标准")
    if rate_raw is None or str(rate_raw).strip() == "":
        reasons.append(REASON_RATE_MISSING)
        rate = None
    else:
        rate = parse_decimal(rate_raw)
        if rate is None:
            reasons.append(REASON_RATE_INVALID)
        elif rate < 0:
            reasons.append(REASON_RATE_NEGATIVE)

    if reasons:
        return BillingDecision(ok=False, amount=None, reasons=tuple(reasons))

    assert days is not None and rate is not None
    return BillingDecision(ok=True, amount=format_amount(days * rate), reasons=())


def present_entry(row: dict[str, Any]) -> dict[str, Any]:
    """输出一条计费单的展示形态：应收金额与计费说明由共用口径现算，列表与详情一致。"""
    item = dict(row)
    decision = evaluate_billing(row)
    item["应收金额"] = decision.amount
    item["计费说明"] = NOTE_BILLABLE if decision.ok else "；".join(decision.reasons)
    return item


def sum_amounts(rows: list[dict[str, Any]]) -> str:
    """汇总若干行的应收金额；不可计费的行不计入。聚合也用同一套 Decimal 口径。"""
    total = Decimal("0")
    for row in rows:
        decision = evaluate_billing(row)
        if decision.ok and decision.amount is not None:
            total += Decimal(decision.amount)
    return format_amount(total)
