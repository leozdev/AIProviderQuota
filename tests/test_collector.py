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

    def assert_stopped(self, pid):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            try:
                if Path('/proc/%d/stat' % pid).read_text().split()[2] == 'Z':
                    return  # No longer running; init will reap the orphan.
            except FileNotFoundError:
                return
            time.sleep(.01)
        self.fail('process %d is still running' % pid)

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
assert first['params']['clientInfo']['version']==sys.argv[1]
print(json.dumps({'id':1,'result':{}}),flush=True)
assert json.loads(sys.stdin.readline())['method']=='initialized'
assert json.loads(sys.stdin.readline())['method']=='account/rateLimits/read'
print(json.dumps({'id':2,'result':{'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':38,'windowDurationMins':10080,'resetsAt':2000000000}}}}}),flush=True)
sys.stdin.read()
'''
        real_popen = subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            version = json.loads((ROOT / 'package/metadata.json').read_text())['KPlugin']['Version']
            child = real_popen([sys.executable, "-c", fake, version], **kwargs)
            children.append(child)
            return child
        with patch.object(collector.subprocess, "Popen", side_effect=launch):
            result = collector.codex_rpc(timeout=3)
        self.assertEqual(result["primary"]["usedPercent"], 38)
        self.assertIsNotNone(children[0].poll())

    def test_malformed_rpc_results_are_source_errors_and_reap_child(self):
        real_popen = subprocess.Popen
        for value in (None, [], {'rateLimitsByLimitId': []}, {'rateLimits': []}):
            with self.subTest(value=value):
                children = []
                fake = "import json,sys; sys.stdin.readline(); print(json.dumps({'id':2,'result':" + repr(value) + "}),flush=True); sys.stdin.read()"
                def launch(*args, **kwargs):
                    child = real_popen([sys.executable, '-c', fake], **kwargs)
                    children.append(child)
                    return child
                with patch.object(collector.subprocess, 'Popen', side_effect=launch):
                    with self.assertRaises(collector.SourceError):
                        collector.codex_rpc(timeout=1)
                self.assertIsNotNone(children[0].poll())

    def test_local_codex_skips_bad_rows_and_disappearing_candidates(self):
        limits = {'primary': {'used_percent': 20, 'window_minutes': 300,
                              'resets_at': self.now + 60}}
        good = {'timestamp': self.now - 5, 'payload': {'type': 'token_count', 'rate_limits': limits}}
        rows = [good, {'timestamp': self.now, 'payload': {'type': 'token_count', 'rate_limits': {}}},
                {'payload': None, 'rate_limits': {}}, ['rate_limits'], 'rate_limits']
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CODEX_HOME=directory):
            sessions = Path(directory) / 'sessions'
            sessions.mkdir()
            valid = sessions / 'rollout-valid.jsonl'
            valid.write_text('\n'.join(json.dumps(row) for row in rows))
            os.utime(valid, (self.now, self.now))
            missing = sessions / 'rollout-disappeared.jsonl'
            with patch.object(Path, 'glob', return_value=iter([missing, valid])):
                observed, snapshot = collector.codex_local_record(self.now)
            self.assertEqual(observed, self.now - 5)
            self.assertEqual(snapshot, limits)

    def test_local_codex_reads_only_eight_newest_files_including_old_directories(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CODEX_HOME=directory):
            sessions = Path(directory) / 'sessions'
            for index in range(12):
                folder = sessions / ('2020' if index == 11 else '2026')
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / ('rollout-%02d.jsonl' % index)
                limits = {'primary': {'used_percent': index, 'window_minutes': 300, 'resets_at': self.now + 60}}
                path.write_text(json.dumps({'timestamp': self.now - 12 + index,
                                           'payload': {'type': 'token_count', 'rate_limits': limits}}))
                os.utime(path, (self.now - 12 + index, self.now - 12 + index))
            real_open, reads = Path.open, []
            def read(path, *args, **kwargs):
                reads.append(path)
                return real_open(path, *args, **kwargs)
            with patch.object(Path, 'open', read):
                observed, snapshot = collector.codex_local_record(self.now)
            self.assertEqual(len(reads), 8)
            self.assertEqual(snapshot['primary']['used_percent'], 11)
            self.assertEqual(observed, self.now - 1)

    def test_local_codex_does_not_read_expired_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, CODEX_HOME=directory):
            sessions = Path(directory) / 'sessions'
            sessions.mkdir()
            path = sessions / 'rollout-expired.jsonl'
            path.write_text('not read')
            os.utime(path, (self.now - 601, self.now - 601))
            with patch.object(Path, 'open', side_effect=AssertionError('expired tail was opened')):
                self.assertIsNone(collector.codex_local_record(self.now))

    def test_slow_provider_has_global_deadline_without_losing_other_results(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, 'CACHE', Path(directory)):
            marker = Path(directory) / 'child.pid'
            def slow():
                child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
                marker.write_text(str(child.pid))
                time.sleep(30)
            sample = collector.report('codex', 'test', [collector.quota_window('7d', 'Semana', 72, self.now + 60)])
            cached = collector.report('ollama', 'test', [collector.quota_window('weekly', 'Semana', 42, self.now + 60)], self.now - 30)
            collector.save_cache('ollama', {'snapshot': cached, 'next_allowed_at': 0})
            started = time.monotonic()
            with patch.object(collector, 'COLLECTION_TIMEOUT', 0.25), patch.object(collector, 'provider_codex', return_value=sample), patch.object(collector, 'provider_claude', side_effect=collector.SourceError('auth', 'expired')), patch.object(collector, 'provider_ollama', side_effect=slow):
                rows = collector.collect(force=True)['providers']
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertEqual([row['state'] for row in rows], ['ok', 'auth', 'stale'])
            self.assertIn('exceeded', rows[2]['message'])
            self.assertEqual(rows[2]['fetched_at'], self.now - 30)
            self.assertEqual(rows[2]['windows'][0]['remaining_percent'], 42)
            child_pid = int(marker.read_text())
            self.assert_stopped(child_pid)

    def test_provider_deadline_also_stops_codex_app_server_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, 'CACHE', Path(directory)):
            marker = Path(directory) / 'rpc-child.pid'
            real_popen = subprocess.Popen
            def launch(*args, **kwargs):
                child = real_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
                marker.write_text(str(child.pid))
                return child
            with patch.object(collector, 'COLLECTION_TIMEOUT', .25), patch.object(collector.subprocess, 'Popen', side_effect=launch):
                value = collector.collect(['codex'], force=True)['providers'][0]
            self.assertEqual(value['state'], 'unavailable')
            child_pid = int(marker.read_text())
            self.assert_stopped(child_pid)
            lock = os.open(Path(directory) / 'collection.lock', os.O_RDWR)
            try:
                collector.fcntl.flock(lock, collector.fcntl.LOCK_EX | collector.fcntl.LOCK_NB)
            finally:
                os.close(lock)

    def test_successful_codex_query_also_stops_app_servers_descendants(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, 'CACHE', Path(directory)):
            marker = Path(directory) / 'grandchild.pid'
            fake = '''import json, pathlib, subprocess, sys, time
marker=sys.argv[1]
child_code='import os,pathlib,signal,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(30)'
subprocess.Popen([sys.executable,'-c',child_code,marker],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
while not pathlib.Path(marker).exists(): time.sleep(.01)
sys.stdin.readline()
print(json.dumps({'id':1,'result':{}}),flush=True)
sys.stdin.readline();sys.stdin.readline()
print(json.dumps({'id':2,'result':{'rateLimits':{'primary':{'usedPercent':28,'windowDurationMins':10080,'resetsAt':2000000000}}}}),flush=True)
sys.stdin.read()
'''
            real_popen = subprocess.Popen
            def launch(*args, **kwargs):
                return real_popen([sys.executable, '-c', fake, str(marker)], **kwargs)
            try:
                with patch.object(collector.subprocess, 'Popen', side_effect=launch):
                    value = collector.collect(['codex'], force=True)['providers'][0]
                self.assertEqual(value['state'], 'ok')
                self.assert_stopped(int(marker.read_text()))
            finally:
                if marker.exists():
                    try:
                        os.kill(int(marker.read_text()), collector.signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_worker_does_not_keep_parent_collection_lock_open(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, 'CACHE', Path(directory)):
            cache = Path(directory)
            marker = cache / 'worker-ready'
            def slow(*args):
                marker.touch()
                time.sleep(30)
            context = collector.multiprocessing.get_context('fork')
            reader, writer = context.Pipe(duplex=False)
            with (cache / 'collection.lock').open('w') as lock:
                collector.fcntl.flock(lock, collector.fcntl.LOCK_EX)
                process = context.Process(target=collector.provider_worker, args=(writer, 'ollama', True, lock.fileno()))
                with patch.object(collector, 'collect_provider', side_effect=slow):
                    process.start()
                writer.close()
                try:
                    deadline = time.monotonic() + 2
                    while not marker.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(marker.exists())
                    lock.close()  # Simulates the supervising parent's descriptor going away.
                    with (cache / 'collection.lock').open('r') as next_lock:
                        collector.fcntl.flock(next_lock, collector.fcntl.LOCK_EX | collector.fcntl.LOCK_NB)
                finally:
                    process.terminate()
                    process.join(timeout=2)
                    process.close()
                    reader.close()

    def test_failed_fork_is_not_retried_as_lock_contention(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, 'CACHE', Path(directory)):
            with patch('multiprocessing.process.BaseProcess.start', side_effect=BlockingIOError('process limit')) as start:
                value = collector.collect(['codex'])['providers'][0]
            self.assertEqual(start.call_count, 1)
            self.assertEqual(value['state'], 'unavailable')
            self.assertIn('start', value['message'])

    def test_second_instance_waits_and_reuses_first_instances_fresh_cache(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, 'CACHE', Path(directory)):
            sample = collector.report('codex', 'test', [collector.quota_window('7d', 'Semana', 72, self.now + 60)])
            cache = Path(directory)
            helper = '''import fcntl,json,pathlib,sys,time
root=pathlib.Path(sys.argv[1])
with (root/'collection.lock').open('w') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 (root/'ready').touch()
 time.sleep(.15)
 (root/'codex.json').write_text(sys.argv[2])
'''
            process = subprocess.Popen([sys.executable, '-c', helper, directory, json.dumps({'snapshot': sample, 'next_allowed_at': 0})])
            try:
                deadline = time.monotonic() + 2
                while not (cache / 'ready').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue((cache / 'ready').exists())
                with patch.object(collector, 'provider_codex', side_effect=AssertionError('duplicate query')):
                    value = collector.collect(['codex'], force=True)['providers'][0]
                self.assertEqual(value['state'], 'ok')
                self.assertEqual(value['message'], '')
            finally:
                process.wait(timeout=2)

    def test_waiting_for_another_instance_is_also_bounded(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, 'CACHE', Path(directory)):
            lock = os.open(Path(directory) / 'collection.lock', os.O_CREAT | os.O_RDWR, 0o600)
            try:
                collector.fcntl.flock(lock, collector.fcntl.LOCK_EX)
                with patch.object(collector, 'COLLECTION_TIMEOUT', .1), patch.object(collector, 'collect_parallel', side_effect=AssertionError('lock bypassed')):
                    started = time.monotonic()
                    value = collector.collect(['codex'])['providers'][0]
                self.assertLess(time.monotonic() - started, 1)
                self.assertEqual(value['state'], 'unavailable')
                self.assertIn('in progress', value['message'])
            finally:
                os.close(lock)

    def test_lock_deadline_preserves_fresh_cache_from_other_instance(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, 'CACHE', Path(directory)):
            sample = collector.report('codex', 'test', [collector.quota_window('7d', 'Semana', 72, self.now + 60)])
            collector.save_cache('codex', {'snapshot': sample, 'next_allowed_at': 0})
            with (Path(directory) / 'collection.lock').open('w') as lock:
                collector.fcntl.flock(lock, collector.fcntl.LOCK_EX)
                with patch.object(collector, 'COLLECTION_TIMEOUT', .1):
                    value = collector.collect(['codex'], force=True)['providers'][0]
            self.assertEqual(value['state'], 'ok')
            self.assertEqual(value['message'], '')

    def test_peer_cache_is_also_reused_if_worker_budget_expires_after_lock_acquisition(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, 'CACHE', Path(directory)):
            sample = collector.report('codex', 'test', [collector.quota_window('7d', 'Semana', 72, self.now + 60)])
            collector.save_cache('codex', {'snapshot': sample, 'next_allowed_at': 0})
            with (Path(directory) / 'collection.lock').open('w') as lock:
                def slow(*args):
                    time.sleep(30)
                with patch.object(collector, 'collect_provider', side_effect=slow):
                    value = collector.collect_parallel(['codex'], False, time.monotonic() + .05,
                                                       lock.fileno(), reuse_fresh=True)[0]
            self.assertEqual(value['state'], 'ok')
            self.assertEqual(value['fetched_at'], sample['fetched_at'])

    def test_lock_deadline_does_not_mask_known_provider_backoff(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, 'CACHE', Path(directory)):
            sample = collector.report('claude', 'test', [collector.quota_window('7d', 'Semana', 72, self.now + 60)])
            collector.save_cache('claude', {'snapshot': sample, 'next_allowed_at': self.now + 90})
            with (Path(directory) / 'collection.lock').open('w') as lock:
                collector.fcntl.flock(lock, collector.fcntl.LOCK_EX)
                with patch.object(collector, 'COLLECTION_TIMEOUT', .05):
                    value = collector.collect(['claude'])['providers'][0]
            self.assertEqual(value['state'], 'stale')
            self.assertNotEqual(value['message'], '')

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
