import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("collector", ROOT / "package/contents/code/quota_collector.py")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


class QuotaContracts(unittest.TestCase):
    def setUp(self):
        self.now = time.time()

    def test_zero_is_reported_and_missing_is_not_zero(self):
        self.assertEqual(collector.quota_window("x", "X", 0)["remaining_percent"], 0)
        self.assertIsNone(collector.quota_window("x", "X", None))
        for invalid in (False, float("nan"), float("inf"), -1, 101):
            self.assertIsNone(collector.percentage(invalid))

    def test_codex_uses_reported_weekly_window_without_inventing_five_hours(self):
        windows = collector.parse_codex({"primary": {"usedPercent": 38, "windowDurationMins": 10080,
                                                    "resetsAt": self.now + 60}, "secondary": None})
        self.assertEqual([(w["key"], w["remaining_percent"]) for w in windows], [("7d", 62)])

    def test_local_and_rpc_codex_shapes_agree(self):
        rpc = collector.parse_codex({"primary": {"usedPercent": 0, "windowDurationMins": 300, "resetsAt": self.now + 60}})
        local = collector.parse_codex({"primary": {"used_percent": 0, "window_minutes": 300, "resets_at": self.now + 60}}, False)
        self.assertEqual(rpc, local)

    def test_claude_unknown_buckets_and_disabled_extra_usage_are_not_quota(self):
        windows = collector.parse_claude({"five_hour": {"utilization": 100, "resets_at": self.now + 60},
                                           "seven_day": {"utilization": 15, "resets_at": self.now + 120},
                                           "unmapped_bonus": {"utilization": 0},
                                           "extra_usage": {"is_enabled": False, "utilization": 0}})
        self.assertEqual([w["remaining_percent"] for w in windows], [0, 85])

    def test_ollama_legacy_remaining_is_not_inverted(self):
        windows = collector.parse_ollama({"included": {"session": {"remaining_percent": 99.54, "resets_at": self.now + 60},
                                                        "weekly": {"remaining_percent": 36.77, "resets_at": self.now + 120}},
                                          "purchased": {"balance_usd": 0}})
        self.assertEqual([w["remaining_percent"] for w in windows], [99.54, 36.77])

    def test_monthly_allowance_and_purchased_credits_remain_separate(self):
        windows = collector.parse_ollama({"included": {"balance_usd": "42.5", "allowance_usd": "60",
                                                        "period": {"until": "2026-11-01T00:00:00Z"}},
                                          "purchased": {"balance_usd": "25"}})
        self.assertAlmostEqual(windows[0]["remaining_percent"], 42.5 / 60 * 100)
        self.assertEqual([w["remaining_usd"] for w in windows], [42.5, 25])
        self.assertIsNone(windows[1]["remaining_percent"])

    def test_zero_or_missing_allowance_does_not_fabricate_percentage(self):
        for allowance in (None, 0):
            windows = collector.parse_ollama({"included": {"balance_usd": 8, "allowance_usd": allowance}})
            self.assertEqual(windows[0]["remaining_usd"], 8)
            self.assertIsNone(windows[0]["remaining_percent"])

    def test_reset_removes_old_window_without_inventing_full_quota(self):
        snapshot = {"windows": [collector.quota_window("5h", "5h", 0, self.now - 1),
                                 collector.quota_window("7d", "Semana", 85, self.now + 60)]}
        self.assertEqual([w["key"] for w in collector.valid_windows(snapshot, self.now)], ["7d"])

    def test_corrupt_cache_shapes_are_discarded(self):
        self.assertEqual(collector.valid_windows({'windows': None}, self.now), [])
        self.assertEqual(collector.valid_windows({'windows': [{'remaining_percent': 50, 'resets_at': 'invalid'}]}, self.now), [])
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, 'CACHE', Path(directory)):
            collector.save_cache('claude', {'snapshot': {'windows': None}, 'next_allowed_at': 'invalid'})
            sample = collector.report('claude', 'test', [collector.quota_window('x', 'X', 50, self.now + 60)])
            with patch.object(collector, 'provider_claude', return_value=sample):
                self.assertEqual(collector.collect_provider('claude', now=self.now)['state'], 'ok')

    def test_auth_error_never_reuses_cached_percentages(self):
        cached = {"snapshot": collector.report("claude", "test", [collector.quota_window("x", "X", 42, self.now + 60)])}
        value = collector.cached_fallback("claude", cached, collector.SourceError("auth", "expired"), self.now)
        self.assertEqual(value["state"], "auth")
        self.assertEqual(value["windows"], [])

    def test_network_error_retains_fresh_data_with_original_timestamp(self):
        snapshot = collector.report("claude", "test", [collector.quota_window("x", "X", 42, self.now + 60)], self.now - 30)
        value = collector.cached_fallback("claude", {"snapshot": snapshot}, collector.SourceError("unavailable", "offline"), self.now)
        self.assertEqual(value["state"], "stale")
        self.assertEqual(value["fetched_at"], self.now - 30)

    def test_old_or_future_cache_is_not_displayed(self):
        for fetched in (self.now - 601, self.now + 30):
            snapshot = collector.report("claude", "test", [collector.quota_window("x", "X", 42, self.now + 60)], fetched)
            value = collector.cached_fallback("claude", {"snapshot": snapshot}, collector.SourceError("unavailable", "offline"), self.now)
            self.assertEqual(value["windows"], [])

    def test_retry_after_prevents_another_provider_request(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, "CACHE", Path(directory)):
            with patch.object(collector, "provider_claude", side_effect=collector.SourceError("rate_limited", "limited", 90)) as fetch:
                collector.collect_provider("claude", True, self.now)
                value = collector.collect_provider("claude", True, self.now + 30)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(value["state"], "rate_limited")

    def test_one_provider_failure_does_not_block_other_sources(self):
        sample = lambda pid: collector.report(pid, "test", [collector.quota_window("x", "X", 50, self.now + 60)])
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, "CACHE", Path(directory)):
            with patch.object(collector, "provider_codex", return_value=sample("codex")), patch.object(collector, "provider_claude", side_effect=collector.SourceError("auth", "expired")), patch.object(collector, "provider_ollama", return_value=sample("ollama")):
                rows = collector.collect(force=True)["providers"]
                self.assertEqual([r["state"] for r in rows], ["ok", "auth", "ok"])
                self.assertEqual(json.loads((Path(directory) / "claude.json").read_text())["snapshot"], None)

    def test_locked_wallet_does_not_attempt_to_open_or_read_key(self):
        calls = []
        def query(method, *args):
            calls.append(method)
            return {"isEnabled": "true", "networkWallet": "test", "isOpen": "false"}[method]
        with patch.object(collector, "qdbus", side_effect=query), patch.object(collector.subprocess, "run") as run:
            with self.assertRaises(collector.SourceError):
                collector.read_ollama_key()
            run.assert_not_called()
        self.assertNotIn("open", calls)

    def test_http_errors_do_not_include_key_or_response_body(self):
        error = urllib.error.HTTPError("https://ollama.com/api/balance", 401, "secret-token", {}, io.BytesIO(b"secret-token"))
        with patch.object(collector.urllib.request.OpenerDirector, "open", side_effect=error):
            with self.assertRaises(collector.SourceError) as captured:
                collector.http_json("https://ollama.com/api/balance", "secret-token")
            self.assertNotIn("secret-token", str(captured.exception))
            self.assertEqual(captured.exception.state, "auth")

    def test_rpc_handshake_and_child_cleanup(self):
        fake = '''import json, sys
first=json.loads(sys.stdin.readline())
assert first['method']=='initialize'
print(json.dumps({'id':1,'result':{}}),flush=True)
assert json.loads(sys.stdin.readline())['method']=='initialized'
assert json.loads(sys.stdin.readline())['method']=='account/rateLimits/read'
print(json.dumps({'id':2,'result':{'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':38,'windowDurationMins':10080,'resetsAt':2000000000}}}}}),flush=True)
sys.stdin.read()
'''
        real_popen = subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            child = real_popen([sys.executable, "-c", fake], **kwargs)
            children.append(child)
            return child
        with patch.object(collector.subprocess, "Popen", side_effect=launch):
            result = collector.codex_rpc(timeout=3)
        self.assertEqual(result["primary"]["usedPercent"], 38)
        self.assertIsNotNone(children[0].poll())

    def test_rpc_timeout_also_terminates_and_reaps_child(self):
        real_popen = subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            child = real_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
            children.append(child)
            return child
        with patch.object(collector.subprocess, 'Popen', side_effect=launch):
            with self.assertRaises(collector.SourceError):
                collector.codex_rpc(timeout=0.05)
        self.assertIsNotNone(children[0].poll())

    def test_store_sends_key_only_through_stdin(self):
        calls = []
        key = 'test-secret-for-stdin-only'
        def run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, '', '')
        def query(method, *args):
            return {'keyDoesNotExist': 'true', 'folderDoesNotExist': 'false'}[method]
        with patch.object(collector, 'wallet_name', return_value='test'), patch.object(collector, 'qdbus', side_effect=query), patch.object(collector.subprocess, 'run', side_effect=run), patch.object(collector.sys, 'stdin', io.StringIO(key+'\n')):
            result = collector.store_ollama_key()
        self.assertTrue(result['stored'])
        self.assertNotIn(key, ' '.join(calls[0][0]))
        self.assertEqual(calls[0][1]['input'], key+'\n')
        self.assertNotIn(key, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
