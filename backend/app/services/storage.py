"""堆存计费业务规则：状态流转、字段校验与筛选口径都收在这里。

金额一律走 app.services.billing 这一份共用实现，在登记/生成账单时算好并
持久化到「应收金额」；列表、详情、导出只读这份存储值，刷新后各处一致。
"""
from __future__ import annotations

from typing import Any

from app.services.billing import BillingError, compute_storage_fee, format_amount
from app.store import store

MODULE = "storage"
REQUIRED_FIELDS = ["计费单号", "关联箱号", "计费周期"]
STATUS_ORDER = ["待核算", "已核算", "已对账", "已开票"]
ACTION_RULES = {"生成账单": "已核算", "确认对账": "已对账", "开具发票": "已开票"}
NEGATIVE_ACTIONS: list[str] = []
# 状态只允许沿 STATUS_ORDER 前进；已开票是终态，不能再改回待对账等任何前置状态。
FINAL_STATUS = STATUS_ORDER[-1]


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
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def preview_fee(self, values: dict[str, Any]) -> tuple[str | None, str]:
        """试算应收金额：与登记、生成账单走同一份口径，结果必然一致。"""
        try:
            return format_amount(compute_storage_fee(values)), ""
        except BillingError as exc:
            return None, str(exc)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        bill_no = str(values.get("计费单号") or "").strip()
        for row in store.rows(MODULE):
            if str(row.get("计费单号", "")).strip() == bill_no:
                return row, f"计费单 {bill_no} 已存在，保留原有记录，不重复生成"
        try:
            amount = compute_storage_fee(values)
        except BillingError as exc:
            return None, str(exc)
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in ("堆存天数", "计费标准", "客户名称"):
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["应收金额"] = format_amount(amount)
        entry["计费状态"] = STATUS_ORDER[0]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, "计费单已登记"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"计费单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于堆存计费可执行范围"
        current = str(entry.get("status") or STATUS_ORDER[0])
        if current == FINAL_STATUS:
            return None, f"计费单{FINAL_STATUS}，不允许再变更状态"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if STATUS_ORDER.index(target) <= STATUS_ORDER.index(current):
            return None, f"计费单当前为「{current}」，不能回退或重复到「{target}」"
        if action == "生成账单":
            try:
                entry["应收金额"] = format_amount(compute_storage_fee(entry))
            except BillingError as exc:
                return None, str(exc)
        entry["status"] = target
        entry["计费状态"] = target
        entry["pending"] = target != FINAL_STATUS
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"计费单已{action}"
