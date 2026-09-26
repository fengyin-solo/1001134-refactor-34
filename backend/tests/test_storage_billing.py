"""堆存计费共用口径的回归测试：金额确定性、统一原因、去重、状态机、列表详情一致。

运行：cd backend && .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import copy
import unittest

from app.services.storage import StorageService
from app.services.storage_billing import (
    REASON_DAYS_NEGATIVE,
    REASON_PERIOD_MISSING,
    evaluate_billing,
    present_entry,
    sum_amounts,
)
from app.store import store


def _valid_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "计费单号": "STOR-9001",
        "关联箱号": "CONT-9001",
        "计费周期": "2026-09-01~2026-09-10",
        "堆存天数": 10,
        "计费标准": "1.25",
        "客户名称": "测试客户",
    }
    values.update(overrides)
    return values


class EvaluateBillingTest(unittest.TestCase):
    def test_amount_is_deterministic_decimal_string(self) -> None:
        decision = evaluate_billing({"计费周期": "2026-09", "堆存天数": 10, "计费标准": "1.25"})
        self.assertTrue(decision.ok)
        self.assertEqual(decision.amount, "12.50")

    def test_rounding_is_half_up_not_float(self) -> None:
        # 2.675 * 3 = 8.025，四舍五入到分是 8.03；浮点直接算容易得到 8.02
        decision = evaluate_billing({"计费周期": "2026-09", "堆存天数": 3, "计费标准": "2.675"})
        self.assertEqual(decision.amount, "8.03")

    def test_zero_days_bills_zero(self) -> None:
        decision = evaluate_billing({"计费周期": "2026-09", "堆存天数": 0, "计费标准": "1.25"})
        self.assertTrue(decision.ok)
        self.assertEqual(decision.amount, "0.00")

    def test_missing_period_reports_reason(self) -> None:
        decision = evaluate_billing({"计费周期": " ", "堆存天数": 10, "计费标准": "1.25"})
        self.assertFalse(decision.ok)
        self.assertIn(REASON_PERIOD_MISSING, decision.reasons)
        self.assertIsNone(decision.amount)

    def test_negative_days_reports_reason(self) -> None:
        decision = evaluate_billing({"计费周期": "2026-09", "堆存天数": -3, "计费标准": "1.25"})
        self.assertFalse(decision.ok)
        self.assertIn(REASON_DAYS_NEGATIVE, decision.reasons)

    def test_non_numeric_days_reports_reason(self) -> None:
        decision = evaluate_billing({"计费周期": "2026-09", "堆存天数": "约十天", "计费标准": "1.25"})
        self.assertFalse(decision.ok)
        self.assertIn("堆存天数不是有效数字", decision.reasons)

    def test_present_entry_marks_unbillable_rows(self) -> None:
        item = present_entry({"计费周期": "", "堆存天数": -3, "计费标准": "1.25"})
        self.assertIsNone(item["应收金额"])
        self.assertIn(REASON_PERIOD_MISSING, item["计费说明"])
        self.assertIn(REASON_DAYS_NEGATIVE, item["计费说明"])

    def test_sum_amounts_skips_unbillable_rows(self) -> None:
        rows = [
            {"计费周期": "2026-09", "堆存天数": 10, "计费标准": "1.25"},
            {"计费周期": "2026-09", "堆存天数": -3, "计费标准": "1.25"},
        ]
        self.assertEqual(sum_amounts(rows), "12.50")


class StorageServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._backup = copy.deepcopy(store.rows("storage"))
        self.service = StorageService()

    def tearDown(self) -> None:
        store.rows("storage")[:] = self._backup

    def test_create_then_duplicate_keeps_single_entry(self) -> None:
        entry, message, ok = self.service.create_entry(_valid_values())
        self.assertTrue(ok)
        self.assertEqual(entry["应收金额"], "12.50")
        count = len(store.rows("storage"))

        again, message, ok = self.service.create_entry(_valid_values())
        self.assertTrue(ok)
        self.assertEqual(again["id"], entry["id"])
        self.assertIn("不重复生成", message)
        self.assertEqual(len(store.rows("storage")), count)

    def test_duplicate_by_container_and_period_keeps_single_entry(self) -> None:
        self.service.create_entry(_valid_values())
        count = len(store.rows("storage"))
        again, message, ok = self.service.create_entry(_valid_values(计费单号="STOR-9002"))
        self.assertTrue(ok)
        self.assertIn("不重复生成", message)
        self.assertEqual(len(store.rows("storage")), count)

    def test_create_with_negative_days_is_rejected_with_reason(self) -> None:
        entry, message, ok = self.service.create_entry(_valid_values(堆存天数=-1))
        self.assertFalse(ok)
        self.assertIsNone(entry)
        self.assertIn(REASON_DAYS_NEGATIVE, message)

    def test_create_with_missing_period_is_rejected_with_reason(self) -> None:
        entry, message, ok = self.service.create_entry(_valid_values(计费周期=""))
        self.assertFalse(ok)
        self.assertIn(REASON_PERIOD_MISSING, message)

    def test_list_and_detail_show_same_amount(self) -> None:
        items, _ = self.service.list_entries(keyword="STOR-0001")
        detail = self.service.get_entry(1)
        self.assertEqual(items[0]["应收金额"], "12.50")
        self.assertEqual(detail["应收金额"], items[0]["应收金额"])
        self.assertEqual(detail["计费说明"], items[0]["计费说明"])

    def test_unbillable_seed_rows_show_reasons_in_list(self) -> None:
        items, _ = self.service.list_entries(keyword="STOR-0005")
        self.assertIsNone(items[0]["应收金额"])
        self.assertIn(REASON_PERIOD_MISSING, items[0]["计费说明"])
        items, _ = self.service.list_entries(keyword="STOR-0006")
        self.assertIn(REASON_DAYS_NEGATIVE, items[0]["计费说明"])

    def test_status_flow_moves_forward_only(self) -> None:
        entry, message, ok = self.service.create_entry(_valid_values())
        entry_id = entry["id"]

        _, message = self.service.run_action(entry_id, "确认对账")
        self.assertIn("需先生成账单", message)

        entry, _ = self.service.run_action(entry_id, "生成账单")
        self.assertEqual(entry["status"], "已核算")
        self.assertEqual(entry["应收金额"], "12.50")

        _, message = self.service.run_action(entry_id, "生成账单")
        self.assertIn("无需重复", message)

        entry, _ = self.service.run_action(entry_id, "确认对账")
        self.assertEqual(entry["status"], "已对账")
        entry, _ = self.service.run_action(entry_id, "开具发票")
        self.assertEqual(entry["status"], "已开票")

    def test_invoiced_entry_cannot_go_back(self) -> None:
        for action in ("生成账单", "确认对账", "开具发票"):
            entry, message = self.service.run_action(4, action)
            self.assertIsNone(entry)
            self.assertIn("不能改回", message)
            self.assertEqual(store.find("storage", 4)["status"], "已开票")

    def test_generate_bill_rechecks_unbillable_row(self) -> None:
        entry, message = self.service.run_action(6, "生成账单")
        self.assertIsNone(entry)
        self.assertIn(REASON_DAYS_NEGATIVE, message)

    def test_summary_matches_list_amounts(self) -> None:
        cards = {card["label"]: card["value"] for card in self.service.summary()}
        items, _ = self.service.list_entries(size=10000)
        billable_total = sum_amounts(items)
        invoiced_total = sum_amounts([row for row in items if row.get("status") == "已开票"])
        self.assertEqual(cards["应收金额合计"], billable_total)
        self.assertEqual(cards["已开票金额"], invoiced_total)
        self.assertEqual(cards["已开票金额"], "30.00")


if __name__ == "__main__":
    unittest.main()
