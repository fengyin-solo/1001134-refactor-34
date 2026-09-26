"""堆存计费接口：维护计费单，覆盖生成账单、确认对账、开具发票等动作。

金额与不可计费原因由 app.services.storage_billing 统一给出；
/summary、/export 等固定路径必须放在 /{entry_id} 之前，否则会被详情路由截获。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.storage import StorageService

router = APIRouter(prefix="/api/storage", tags=["堆存计费"])

service = StorageService()

LIST_FIELDS = ["计费单号", "关联箱号", "计费周期", "堆存天数", "计费标准", "应收金额", "客户名称", "计费状态", "计费说明"]
STATUSES = ["待核算", "已核算", "已对账", "已开票"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按计费单号检索"),
    status: str | None = Query(default=None, description="待核算、已核算、已对账、已开票"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按计费单号与状态过滤堆存计费列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summary() -> dict[str, Any]:
    """堆存计费看板：待核算单数、应收金额合计、已开票金额，与列表同一口径。"""
    return {"module": "storage", "cards": service.summary()}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出堆存计费清单：返回当前过滤条件下的全量数据，金额口径与列表一致。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "storage", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条计费单明细；与列表共用同一展示口径，刷新后金额一致。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"计费单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条计费单：缺字段、周期缺失、天数为负会说明原因；重复生成只保留原记录。"""
    entry, message, ok = service.create_entry(payload.values)
    return ActionResult(ok=ok, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条计费单执行生成账单、确认对账、开具发票；已开票不能改回待对账。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
