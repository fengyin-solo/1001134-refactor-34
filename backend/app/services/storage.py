"""堆存计费业务规则：状态流转、字段校验与筛选口径都收在这里。

金额计算、不可计费原因、展示形态统一走 app.services.storage_billing，
本文件只负责流程：登记去重、状态机守卫、列表/详情/汇总都经同一展示函数输出。
"""
from __future__ import annotations

from typing import Any

from app.services.storage_billing import evaluate_billing, present_entry, sum_amounts
from app.store import store

MODULE = "storage"
# 身份字段在登记时缺一不可；计费周期、堆存天数、计费标准属于计费口径，
# 由 storage_billing.evaluate_billing 统一校验并给出原因文案。
REQUIRED_FIELDS = ["计费单号", "关联箱号"]
# 登记时落入存储的字段全集：身份字段 + 计费口径字段 + 展示字段
STORED_FIELDS = ["计费单号", "关联箱号", "计费周期", "堆存天数", "计费标准", "客户名称"]
STATUS_ORDER = ["待核算", "已核算", "已对账", "已开票"]
TERMINAL_STATUS = "已开票"
# 动作 → (允许执行的当前状态, 目标状态)，只允许逐级向前，已开票是终态
TRANSITIONS = {
    "生成账单": ("待核算", "已核算"),
    "确认对账": ("已核算", "已对账"),
    "开具发票": ("已对账", "已开票"),
}
NEXT_ACTION = {"待核算": "生成账单", "已核算": "确认对账", "已对账": "开具发票"}


class StorageService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("计费单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [present_entry(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        return present_entry(row)

    def summary(self) -> list[dict[str, Any]]:
        """看板卡片：待核算单数、应收金额合计、已开票金额，聚合口径与列表一致。"""
        rows = store.rows(MODULE)
        pending = sum(1 for row in rows if row.get("status") == STATUS_ORDER[0])
        invoiced = [row for row in rows if row.get("status") == TERMINAL_STATUS]
        return [
            {"label": "待核算计费单", "value": pending},
            {"label": "应收金额合计", "value": sum_amounts(rows)},
            {"label": "已开票金额", "value": sum_amounts(invoiced)},
        ]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}", False

        duplicate = self._find_duplicate(values)
        if duplicate is not None:
            message = (
                f"计费单 {duplicate.get('计费单号')} 已存在"
                f"（关联箱号 {duplicate.get('关联箱号')}、计费周期 {duplicate.get('计费周期')}），"
                "保留原记录不重复生成"
            )
            return present_entry(duplicate), message, True

        decision = evaluate_billing(values)
        if not decision.ok:
            return None, "；".join(decision.reasons), False

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in STORED_FIELDS:
            if field in values:
                entry[field] = values.get(field)
        entry["应收金额"] = decision.amount
        entry["status"] = STATUS_ORDER[0]
        entry["计费状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return present_entry(entry), "计费单已登记", True

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"计费单 {entry_id} 不存在或已归档"
        if action not in TRANSITIONS:
            return None, f"动作「{action}」不属于堆存计费可执行范围"

        current = str(entry.get("status") or "")
        source, target = TRANSITIONS[action]
        if current == TERMINAL_STATUS:
            return None, f"计费单 {entry_id} 已开票，不能改回待对账或重新核算"
        if current == target:
            return None, f"计费单已是「{target}」，无需重复{action}"
        if current != source:
            if current in NEXT_ACTION:
                return None, f"当前状态「{current}」不能执行{action}，需先{NEXT_ACTION[current]}"
            return None, f"当前状态「{current}」不能执行{action}"

        if action == "生成账单":
            decision = evaluate_billing(entry)
            if not decision.ok:
                return None, "；".join(decision.reasons)
            entry["应收金额"] = decision.amount

        entry["status"] = target
        entry["计费状态"] = target
        entry["pending"] = target != TERMINAL_STATUS
        entry["abnormal"] = False
        return present_entry(entry), f"计费单已{action}"

    def _find_duplicate(self, values: dict[str, Any]) -> dict[str, Any] | None:
        """重复生成的判定：计费单号相同，或同一关联箱号在同一计费周期已生成过。"""
        bill_no = str(values.get("计费单号") or "").strip()
        container = str(values.get("关联箱号") or "").strip()
        period = str(values.get("计费周期") or "").strip()
        for row in store.rows(MODULE):
            if bill_no and str(row.get("计费单号") or "").strip() == bill_no:
                return row
            if (
                container
                and period
                and str(row.get("关联箱号") or "").strip() == container
                and str(row.get("计费周期") or "").strip() == period
            ):
                return row
        return None
