# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Decisions of the item sync and the run guard that need no site."""

import unittest
from collections import namedtuple
from unittest import mock

import frappe

from alaiy_os_connector_cloudstore.cloudstore import run_guard, sync_items

Usage = namedtuple("Usage", "total used free")
GB = 1024**3


class TestFinalStatus(unittest.TestCase):
    def test_every_item_failing_is_a_failure(self):
        status, message = sync_items._final_status({"processed": 0, "failed": 5}, "")
        self.assertEqual(status, "failed")
        self.assertIn("Every item failed (5)", message)

    def test_some_failures_among_successes_stay_a_success(self):
        self.assertEqual(sync_items._final_status({"processed": 10, "failed": 1}, ""), ("success", ""))

    def test_an_empty_run_is_a_success(self):
        self.assertEqual(sync_items._final_status({"processed": 0, "failed": 0}, ""), ("success", ""))

    def test_a_stock_failure_fails_the_run_with_its_reason(self):
        status, message = sync_items._final_status({"processed": 3, "failed": 0}, "no valuation rate")
        self.assertEqual(status, "failed")
        self.assertIn("no valuation rate", message)

    def test_all_items_failing_wins_over_a_stock_failure(self):
        self.assertIn("Every item failed", sync_items._final_status({"processed": 0, "failed": 2}, "x")[1])


class TestLowDisk(unittest.TestCase):
    def _check(self, free_gb, conf=None, datadir="/data"):
        with mock.patch.object(frappe, "conf", conf or {}, create=True), \
                mock.patch.object(frappe, "get_site_path", return_value="/site", create=True), \
                mock.patch.object(frappe, "db", mock.Mock(sql=mock.Mock(return_value=[[datadir]])), create=True), \
                mock.patch("shutil.disk_usage", return_value=Usage(34 * GB, 0, int(free_gb * GB))):
            return run_guard.low_disk()

    def test_plenty_of_space_runs(self):
        self.assertIsNone(self._check(16))

    def test_under_the_default_floor_skips_with_a_reason(self):
        message = self._check(0.4)
        self.assertIn("0.4 GB of disk is free", message)
        self.assertIn("minimum 1 GB", message)

    def test_the_floor_is_configurable_and_zero_turns_it_off(self):
        self.assertIsNone(self._check(2, {"cloudstore_min_free_gb": 1.5}))
        self.assertIsNotNone(self._check(1, {"cloudstore_min_free_gb": 1.5}))
        self.assertIsNone(self._check(0.01, {"cloudstore_min_free_gb": 0}))

    def test_a_bad_setting_falls_back_to_the_default(self):
        self.assertIsNotNone(self._check(0.4, {"cloudstore_min_free_gb": "lots"}))
        self.assertIsNone(self._check(16, {"cloudstore_min_free_gb": "lots"}))

    def test_a_check_that_cannot_run_never_blocks(self):
        with mock.patch.object(frappe, "conf", {}, create=True), \
                mock.patch.object(frappe, "get_site_path", side_effect=OSError, create=True), \
                mock.patch.object(frappe, "db", mock.Mock(sql=mock.Mock(side_effect=Exception)), create=True), \
                mock.patch("shutil.disk_usage", side_effect=OSError):
            self.assertIsNone(run_guard.low_disk())
