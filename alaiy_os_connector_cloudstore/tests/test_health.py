# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""The stock freshness check: do the quantities held in ERPNext still match what Cloudstore reports?

The decision is plain Python and runs without a site. A sample of items is compared with a live lookup;
a few differences are normal (sales and in-flight changes between syncs), widespread ones mean the stock
sync is stale.
"""

import unittest

from alaiy_os_connector_cloudstore.cloudstore.health import first_item, judge, live_quantity


def pairs(total, differing):
    return [(5.0, 9.0 if i < differing else 5.0) for i in range(total)]


class JudgeTests(unittest.TestCase):
    def test_matching_stock_is_ok(self):
        check = judge(pairs(10, 0))
        self.assertEqual((check["key"], check["state"]), ("stock_freshness", "ok"))
        self.assertIn("0 of 10", check["detail"])

    def test_a_couple_of_differences_are_normal(self):
        self.assertEqual(judge(pairs(10, 2))["state"], "ok")

    def test_three_in_ten_warn_and_six_in_ten_are_red(self):
        self.assertEqual(judge(pairs(10, 3))["state"], "warn")
        self.assertEqual(judge(pairs(10, 5))["state"], "warn")
        self.assertEqual(judge(pairs(10, 6))["state"], "red")
        self.assertEqual(judge(pairs(10, 10))["state"], "red")

    def test_the_thresholds_are_a_share_of_the_sample_not_a_count(self):
        self.assertEqual(judge(pairs(5, 1))["state"], "ok")
        self.assertEqual(judge(pairs(5, 2))["state"], "warn")
        self.assertEqual(judge(pairs(5, 3))["state"], "red")

    def test_too_few_comparable_items_is_unknown_not_ok(self):
        check = judge(pairs(4, 0))
        self.assertEqual(check["state"], "unknown")
        self.assertIn("4", check["detail"])
        self.assertEqual(judge([])["state"], "unknown")

    def test_a_tiny_difference_in_a_decimal_quantity_is_not_a_difference(self):
        self.assertEqual(judge([(5.00001, 5.0)] * 10)["state"], "ok")

    def test_items_that_could_not_be_checked_are_mentioned(self):
        check = judge(pairs(8, 0), unreadable=2)
        self.assertIn("2 could not be checked", check["detail"])

    def test_the_detail_names_no_item(self):
        self.assertNotIn("SKU", judge(pairs(10, 6))["detail"])


class LiveQuantityTests(unittest.TestCase):
    def test_the_item_quantity_is_used_when_given(self):
        self.assertEqual(live_quantity({"qty": 7}), 7.0)

    def test_an_oversold_quantity_is_held_at_zero(self):
        self.assertEqual(live_quantity({"qty": -3}), 0.0)

    def test_the_warehouse_rows_are_summed_when_there_is_no_total(self):
        self.assertEqual(live_quantity({"whs": [{"qty": 2}, {"qty": 3}]}), 5.0)
        self.assertEqual(live_quantity({"qty": None, "whs": [{"qty": 2}, {"qty": -9}]}), 2.0)

    def test_a_missing_item_has_no_stock(self):
        self.assertEqual(live_quantity(None), 0.0)
        self.assertEqual(live_quantity({}), 0.0)


class FirstItemTests(unittest.TestCase):
    def test_a_single_item_reply(self):
        self.assertEqual(first_item({"content": {"sku": "A1", "qty": 2}}, "A1"), {"sku": "A1", "qty": 2})

    def test_a_list_reply_picks_the_exact_sku(self):
        reply = {"content": [{"sku": "A10"}, {"sku": "A1", "qty": 4}]}
        self.assertEqual(first_item(reply, "A1"), {"sku": "A1", "qty": 4})

    def test_no_match_or_an_empty_reply_is_none(self):
        self.assertIsNone(first_item({"content": [{"sku": "A10"}]}, "A1"))
        self.assertIsNone(first_item({}, "A1"))
        self.assertIsNone(first_item(None, "A1"))


if __name__ == "__main__":
    unittest.main()
