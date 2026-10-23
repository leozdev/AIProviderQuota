#!/usr/bin/env python3
"""Cotas de IA: bounded, read-only quota collection, with no inference calls.

Codex RPC lifecycle/normalization adapted from Marc Cheng's PlasmaWidgetAiUsage
(MIT), revision 1b8fef4f2ca78482d8ca289a4204f02e5c51e111. See LICENSE/NOTICE.
"""
import argparse
import datetime as dt
import fcntl
import getpass
import heapq
import json
import math
import multiprocessing
from multiprocessing.connection import wait
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

VERSION = json.loads((Path(__file__).resolve().parents[2] / "metadata.json").read_text())["KPlugin"]["Version"]
FOLDER = "AI Quotas"
ENTRY = "ollama-cloud-api-key"
MAX_AGE = 600
MAX_BODY = 1024 * 1024
COLLECTION_TIMEOUT = 20
PROVIDERS = ("codex", "claude", "ollama")
LABELS = {"codex": "Codex", "claude": "Claude", "ollama": "Ollama Cloud"}
CACHE = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "ai-quotas"


class SourceError(Exception):
    def __init__(self, state, message, retry_after=0):
        super().__init__(message)
        self.state = state
        self.message = message
        self.retry_after = retry_after


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def percentage(value):
    value = number(value)
    return value if value is not None and 0 <= value <= 100 else None


def timestamp(value):
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (ValueError, OverflowError):
            return None
    value = number(value)
    return value if value is not None and 0 < value < 253402300800 else None


def quota_window(key, label, remaining, resets=None, **extra):
    pct = percentage(remaining)
    if pct is None and extra.get("remaining_usd") is None:
        return None
    return {"key": key, "label": label, "remaining_percent": pct,
            "resets_at": timestamp(resets), **extra}


def report(pid, source, windows, fetched_at=None, **extra):
    windows = [w for w in windows if w is not None]
    if not windows:
        raise SourceError("unavailable", 'The provider returned no usable quota.')
    return {"id": pid, "label": LABELS[pid], "state": "ok", "message": "",
            "source": source, "fetched_at": fetched_at or time.time(),
            "windows": windows, **extra}


def valid_windows(snapshot, now):
    if not isinstance(snapshot, dict):
        return []
    windows = snapshot.get("windows")
    if not isinstance(windows, list):
        return []
    valid = []
    for window in windows:
        if not isinstance(window, dict):
            continue
        reset = timestamp(window.get("resets_at"))
        if window.get("resets_at") is not None and (reset is None or reset <= now):
            continue
        pct = percentage(window.get("remaining_percent"))
        amount = number(window.get("remaining_usd"))
        if pct is None and amount is None:
            continue
        valid.append({**window, "resets_at": reset, "remaining_percent": pct})
    return valid


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_json(url, token, oauth=False):
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json",
               "User-Agent": "plasma-ai-quotas/" + VERSION}
    if oauth:
        headers["anthropic-beta"] = "oauth-2025-04-20"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=8) as response:
            body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise SourceError("unavailable", 'The provider response exceeded the size limit.')
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("object expected")
        return value
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in (401, 403):
            raise SourceError("auth", 'Authentication was rejected. Renew the login or key.') from None
        if exc.code == 429:
            retry = number(exc.headers.get("Retry-After"))
            raise SourceError("rate_limited", 'Queries are temporarily rate-limited by the provider.',
                              min(86400, max(30, retry or 300))) from None
        raise SourceError("unavailable", 'Query unavailable (HTTP %d).' % exc.code) from None
    except (OSError, ValueError, TimeoutError):
        raise SourceError("unavailable", 'Could not query the provider. Check your connection.') from None


def qdbus(method, *args):
    binary = shutil.which("qdbus6") or "/usr/lib/qt6/bin/qdbus"
    try:
        result = subprocess.run([binary, "org.kde.kwalletd6", "/modules/kwalletd6",
                                 "org.kde.KWallet." + method, *map(str, args)],
                                capture_output=True, text=True, timeout=4, check=False)
    except (OSError, subprocess.SubprocessError):
        raise SourceError("auth", 'KWallet is unavailable in this session.') from None
    if result.returncode:
        raise SourceError("auth", 'Could not access KWallet.')
    return result.stdout.strip()


def wallet_name():
    if qdbus("isEnabled") != "true":
        raise SourceError("auth", 'Enable KWallet to access the Ollama key.')
    wallet = qdbus("networkWallet")
    if not wallet or qdbus("isOpen", wallet) != "true":
        raise SourceError("auth", 'Unlock KWallet to query Ollama Cloud.')
    return wallet


def read_ollama_key():
    wallet = wallet_name()
    if qdbus("keyDoesNotExist", wallet, FOLDER, ENTRY) == "true":
        raise SourceError("auth", 'Configure the Ollama key in KWallet.')
    try:
        result = subprocess.run(["kwallet-query", "-f", FOLDER, "-r", ENTRY, wallet],
                                capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        raise SourceError("auth", 'Could not read the key from KWallet.') from None
    key = result.stdout.strip()
    if result.returncode or not key or len(key) > 512 or any(c.isspace() for c in key):
        raise SourceError("auth", 'The Ollama key is unavailable in KWallet.')
    return key


def store_ollama_key(replace=False, gui=False):
    wallet = wallet_name()
    if not replace and qdbus("keyDoesNotExist", wallet, FOLDER, ENTRY) != "true":
        raise SourceError("auth", 'A key already exists. Use --replace to replace it.')
    if gui:
        try:
            prompt = subprocess.run(["kdialog", "--title", 'AI Quotes', "--password",
                                     'Ollama Cloud API key (replaces the previous key):'],
                                    capture_output=True, text=True, check=False, timeout=300)
        except (OSError, subprocess.SubprocessError):
            raise SourceError("auth", 'Could not open key configuration.') from None
        if prompt.returncode:
            return {"stored": False, "cancelled": True}
        key = prompt.stdout.strip()
    else:
        key = getpass.getpass('Ollama Cloud key: ') if sys.stdin.isatty() else sys.stdin.readline().strip()
    if not key or len(key) > 512 or any(c.isspace() for c in key):
        raise SourceError("auth", 'Empty or invalid key.')
    try:
        if qdbus("folderDoesNotExist", wallet, FOLDER) == "true":
            # Keep one D-Bus connection alive while using the wallet handle.
            # python-dbus is needed only for this initial folder setup; normal
            # collection uses the existing qdbus6/kwallet-query executables.
            try:
                import dbus
                bus = dbus.SessionBus()
                service = dbus.Interface(bus.get_object("org.kde.kwalletd6", "/modules/kwalletd6"), "org.kde.KWallet")
                handle = service.open(wallet, dbus.Int64(0), "kwallet-query", timeout=10)
                if int(handle) < 0:
                    raise SourceError("auth", 'KWallet did not authorize access.')
                try:
                    if not service.createFolder(handle, FOLDER, "kwallet-query"):
                        raise SourceError("auth", 'Could not create the folder in KWallet.')
                finally:
                    service.close(handle, False, "kwallet-query")
            except SourceError:
                raise
            except Exception:
                raise SourceError("auth", 'Create the AI Quotas folder in KWallet and try again.') from None
        result = subprocess.run(["kwallet-query", "-f", FOLDER, "-w", ENTRY, wallet],
                                input=key + "\n", capture_output=True, text=True,
                                timeout=10, check=False)
        if result.returncode:
            raise SourceError("auth", 'Could not store the key in KWallet.')
    finally:
        key = None
    return {"stored": True, "location": "KWallet", "folder": FOLDER, "entry": ENTRY}


def codex_window_identity(slot, minutes):
    # Adapted from upstream: labels reflect returned durations, never assumed 5h/7d.
    if minutes == 10080:
        return "7d", 'Weekly'
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        return slot, 'Window'
    if minutes % 1440 == 0:
        return str(minutes // 1440) + "d", str(minutes // 1440) + ' days'
    if minutes % 60 == 0:
        return str(minutes // 60) + "h", str(minutes // 60) + "h"
    return str(minutes) + "m", str(minutes) + " min"


def parse_codex(snapshot, camel_case=True):
    if not isinstance(snapshot, dict):
        return []
    windows = []
    for slot in ("primary", "secondary"):
        block = snapshot.get(slot)
        if not isinstance(block, dict):
            continue
        used = percentage(block.get("usedPercent" if camel_case else "used_percent"))
        reset = timestamp(block.get("resetsAt" if camel_case else "resets_at"))
        minutes = block.get("windowDurationMins" if camel_case else "window_minutes")
        if used is None or reset is None:
            continue
        key, label = codex_window_identity(slot, minutes)
        windows.append(quota_window(key, label, 100 - used, reset))
    return windows


def codex_rpc(timeout=7):
    choices = [Path.home() / ".local/bin/codex", shutil.which("codex")]
    binary = next((str(p) for p in choices if p and os.access(p, os.X_OK)), None)
    if not binary:
        raise SourceError("unavailable", 'Codex client not found.')
    process = None
    # In a provider worker the app-server shares its supervised process group.
    # Direct CLI/test calls keep their own group for the same cleanup guarantee.
    own_group = multiprocessing.parent_process() is None
    selector = selectors.DefaultSelector()
    try:
        process = subprocess.Popen([binary, "app-server", "--listen", "stdio://"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=own_group)
        def send(value):
            process.stdin.write((json.dumps(value) + "\n").encode())
            process.stdin.flush()
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "plasma-ai-quotas", "version": VERSION}}})
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        deadline, buffered, received = time.monotonic() + timeout, b"", 0
        while time.monotonic() < deadline:
            events = selector.select(max(0, deadline - time.monotonic()))
            for stream, _ in events:
                chunk = os.read(stream.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(stream.fileobj)
                    continue
                received += len(chunk)
                if received > MAX_BODY:
                    raise SourceError("unavailable", 'The Codex response exceeded the size limit.')
                if stream.data == "stderr":
                    continue
                buffered += chunk
                while b"\n" in buffered:
                    line, buffered = buffered.split(b"\n", 1)
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        continue
                    if value.get("error") is not None:
                        raise SourceError("unavailable", 'The Codex quota query was rejected.')
                    if value.get("id") == 1:
                        send({"method": "initialized", "params": {}})
                        send({"id": 2, "method": "account/rateLimits/read", "params": {}})
                    if value.get("id") == 2:
                        result = value.get("result")
                        if isinstance(result, dict):
                            by_id = result.get("rateLimitsByLimitId")
                            snapshot = by_id.get("codex") if isinstance(by_id, dict) else None
                            if not isinstance(snapshot, dict) or not snapshot:
                                snapshot = result.get("rateLimits")
                            if isinstance(snapshot, dict):
                                return snapshot
                        raise SourceError("unavailable", 'The Codex client returned no valid limits.')
            if process.poll() is not None and not selector.get_map():
                break
        raise SourceError("unavailable", 'The Codex query timed out.')
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SourceError("unavailable", 'Could not query the Codex client.') from None
    finally:
        selector.close()
        if process is not None:
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process.poll() is None:
                try:
                    (os.killpg if own_group else os.kill)(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    try:
                        (os.killpg if own_group else os.kill)(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=2)
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()


def codex_local_record(now):
    root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "sessions"
    def candidates():
        # A long-lived active session may be in an old date directory. Select
        # by file modification time, retaining only eight candidates in memory.
        for path in root.glob("**/rollout-*.jsonl"):
            try:
                yield (path.stat().st_mtime, path)
            except OSError:
                continue
    files = heapq.nlargest(8, candidates(), key=lambda row: row[0])
    best = None
    for modified, path in files:
        # Session logs are append-only; an untouched file cannot contain a new
        # quota observation. Keep scanning old directories, but skip old tails.
        if modified < now - MAX_AGE:
            continue
        try:
            with path.open("rb") as file:
                size = file.seek(0, 2)
                offset = max(0, size - MAX_BODY)
                file.seek(offset)
                if offset:
                    file.readline()
                lines = file.read(MAX_BODY).splitlines()
            for line in reversed(lines):
                if b'"rate_limits"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                observed = timestamp(row.get("timestamp"))
                if (payload.get("type") == "token_count" and isinstance(payload.get("rate_limits"), dict)
                        and observed is not None and now - MAX_AGE <= observed <= now
                        and parse_codex(payload["rate_limits"], False)):
                    if best is None or observed > best[0]:
                        best = (observed, payload["rate_limits"])
                    break
        except OSError:
            continue
    return best


def provider_codex():
    try:
        return report("codex", 'Codex · live query', parse_codex(codex_rpc()))
    except SourceError as error:
        found = codex_local_record(time.time())
        if found:
            return report("codex", 'Codex · local session log', parse_codex(found[1], False),
                          fetched_at=found[0], message='Data from the latest Codex session.')
        raise error


def parse_claude(data):
    windows = []
    for key, label in (("five_hour", "5h"), ("seven_day", 'Weekly'),
                       ("seven_day_opus", 'Opus · weekly'), ("seven_day_sonnet", 'Sonnet · weekly')):
        block = data.get(key)
        if isinstance(block, dict):
            used = percentage(block.get("utilization"))
            if used is not None:
                windows.append(quota_window(key, label, 100 - used, block.get("resets_at")))
    return windows


def provider_claude():
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
    try:
        auth = json.loads((root / ".credentials.json").read_text())["claudeAiOauth"]
        token = auth["accessToken"]
        expiry = number(auth.get("expiresAt"))
    except (OSError, ValueError, KeyError, TypeError):
        raise SourceError("auth", 'Sign in through Claude Code.') from None
    if not isinstance(token, str) or not token:
        raise SourceError("auth", 'Sign in through Claude Code.')
    if expiry is not None and expiry / 1000 <= time.time():
        raise SourceError("auth", 'Session expired. Open Claude Code to renew the login.')
    data = http_json("https://api.anthropic.com/api/oauth/usage", token, oauth=True)
    return report("claude", 'Claude · internal query', parse_claude(data))


def parse_ollama(data):
    included = data.get("included")
    if not isinstance(included, dict):
        return []
    windows = []
    for key, label in (("session", 'Session'), ("weekly", 'Weekly')):
        block = included.get(key)
        if isinstance(block, dict):
            windows.append(quota_window(key, label, block.get("remaining_percent"), block.get("resets_at")))
    balance = number(included.get("balance_usd"))
    allowance = number(included.get("allowance_usd"))
    if balance is not None and balance >= 0:
        ratio = balance / allowance * 100 if allowance is not None and allowance > 0 else None
        period = included.get("period") or {}
        windows.append(quota_window("monthly", 'Monthly', ratio, period.get("until"),
                                    remaining_usd=balance, allowance_usd=allowance))
    purchased = number((data.get("purchased") or {}).get("balance_usd"))
    if purchased is not None and purchased > 0:
        windows.append(quota_window("purchased", 'Purchased credits', None,
                                    remaining_usd=purchased, allowance_usd=None))
    return windows


def provider_ollama():
    data = http_json("https://ollama.com/api/balance", read_ollama_key())
    return report("ollama", 'Ollama Cloud · account balance', parse_ollama(data))


def load_cache(pid):
    try:
        value = json.loads((CACHE / (pid + ".json")).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(pid, value):
    CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=pid + "-", suffix=".tmp", dir=CACHE)
    try:
        with os.fdopen(descriptor, "w") as file:
            json.dump(value, file, allow_nan=False)
        os.replace(name, CACHE / (pid + ".json"))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def unavailable(pid, state, message):
    return {"id": pid, "label": LABELS[pid], "state": state, "message": message,
            "source": "", "fetched_at": None, "windows": []}


def cached_fallback(pid, cached, error, now):
    snapshot = cached.get("snapshot")
    fetched = timestamp(snapshot.get("fetched_at")) if isinstance(snapshot, dict) else None
    windows = valid_windows(snapshot, now)
    if error.state not in ("auth",) and fetched and 0 <= now - fetched <= MAX_AGE and windows:
        return {**snapshot, "state": "stale", "message": error.message, "windows": windows}
    return unavailable(pid, error.state, error.message)


def fresh_snapshot(cached, now):
    next_allowed = number(cached.get("next_allowed_at"))
    if next_allowed is not None and next_allowed > now:
        return None
    snapshot = cached.get("snapshot")
    if isinstance(snapshot, dict):
        fetched = timestamp(snapshot.get("fetched_at"))
        windows = valid_windows(snapshot, now)
        if fetched and 0 <= now - fetched < 20 and windows:
            return {**snapshot, "windows": windows}
    return None


def collect_provider(pid, force=False, now=None):
    now = time.time() if now is None else now
    cached = load_cache(pid)
    next_allowed = number(cached.get("next_allowed_at"))
    if next_allowed is not None and next_allowed > now:
        return cached_fallback(pid, cached, SourceError("rate_limited", 'Waiting for the provider rate limit.'), now)
    fresh = fresh_snapshot(cached, now) if not force else None
    if fresh:
        return fresh
    try:
        value = {"codex": provider_codex, "claude": provider_claude, "ollama": provider_ollama}[pid]()
        value["windows"] = valid_windows(value, time.time())
        if not value["windows"]:
            raise SourceError("unavailable", 'The window reset. Waiting for a new valid query.')
        save_cache(pid, {"snapshot": value, "next_allowed_at": 0})
        return value
    except SourceError as error:
        save_cache(pid, {"snapshot": None if error.state == "auth" else cached.get("snapshot"),
                         "next_allowed_at": now + error.retry_after if error.retry_after else 0})
        return cached_fallback(pid, cached, error, now)
    except Exception:
        # Never expose raw exceptions: a library can include HTTP headers or credentials.
        return unavailable(pid, "unavailable", 'Could not parse the provider response.')


def provider_worker(connection, pid, force, lock_fd):
    # A separate process lets the parent enforce a wall-clock deadline even
    # during DNS resolution. Wallet CLI children share this process group.
    os.close(lock_fd)  # Only the supervising parent owns the collection lock.
    os.setsid()
    try:
        connection.send(collect_provider(pid, force))
    finally:
        connection.close()


def collect_parallel(selected, force, deadline, lock_fd, reuse_fresh=False):
    context = multiprocessing.get_context("fork")  # Plasma targets Linux.
    workers, rows = {}, {}
    try:
        for pid in selected:
            reader, writer = context.Pipe(duplex=False)
            process = context.Process(target=provider_worker, args=(writer, pid, force, lock_fd))
            try:
                process.start()
            except OSError:
                reader.close()
                process.close()
                rows[pid] = unavailable(pid, "unavailable", 'Could not start provider collection.')
                continue
            finally:
                writer.close()
            workers[reader] = (pid, process)
        pending = set(workers)
        while pending and time.monotonic() < deadline:
            for reader in wait(pending, timeout=max(0, deadline - time.monotonic())):
                pid, _ = workers[reader]
                try:
                    rows[pid] = reader.recv()
                except EOFError:
                    rows[pid] = unavailable(pid, "unavailable", 'Provider collection was interrupted.')
                pending.remove(reader)
        for reader in pending:
            pid, _ = workers[reader]
            cached, now = load_cache(pid), time.time()
            fresh = fresh_snapshot(cached, now) if reuse_fresh else None
            rows[pid] = fresh or cached_fallback(pid, cached, SourceError(
                "unavailable", 'The provider exceeded the query time limit.'), now)
        return [rows[pid] for pid in selected]
    finally:
        for reader, (_, process) in workers.items():
            reader.close()
            # Clean the group even after a successful result: an app-server
            # may leave a helper behind after its own PID exits.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                if process.is_alive():
                    process.terminate()
            process.join(timeout=0.2)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.is_alive():
                process.kill()
            process.join()
            process.close()


def collect(selected=PROVIDERS, force=False):
    deadline = time.monotonic() + COLLECTION_TIMEOUT
    CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = os.open(CACHE / "collection.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        waited = False
        rows = None
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                waited = True
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            else:
                rows = collect_parallel(selected, force and not waited, deadline, lock, reuse_fresh=waited)
                break
        if rows is None:
            rows = []
            for pid in selected:
                cached, now = load_cache(pid), time.time()
                rows.append(fresh_snapshot(cached, now) or cached_fallback(pid, cached, SourceError(
                    "unavailable", 'Refresh in progress.'), now))
        return {"schema_version": 1, "generated_at": time.time(), "max_age_sec": MAX_AGE, "providers": rows}
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description='Subscription quota collector for Plasma.')
    parser.add_argument("--providers", default=",".join(PROVIDERS))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--configure-ollama", action="store_true", help='Read a key from standard input and store it in KWallet')
    parser.add_argument("--gui", action="store_true", help='Prompt for the key in a password dialog')
    parser.add_argument("--replace", action="store_true", help='Allow replacing the existing KWallet entry')
    args = parser.parse_args()
    if args.configure_ollama:
        try:
            print(json.dumps(store_ollama_key(args.replace, args.gui), ensure_ascii=False))
        except (SourceError, subprocess.SubprocessError) as exc:
            print(json.dumps({"stored": False, "message": exc.message if isinstance(exc, SourceError) else 'KWallet did not respond.'}, ensure_ascii=False))
            return 1
        return 0
    selected = [pid for pid in PROVIDERS if pid in args.providers.split(",")]
    print(json.dumps(collect(selected, args.force), ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
