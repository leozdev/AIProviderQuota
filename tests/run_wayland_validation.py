"""Render in an isolated KWin session; never replace the user's compositor."""
import argparse
from pathlib import Path
import os
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
(ROOT / 'evidence').mkdir(exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('--plasma', action='store_true')
parser.add_argument('--plasma-fixture', action='store_true', help='Native Plasma with fake collector; no accounts')
parser.add_argument('--work-dir', type=Path, default=Path(tempfile.gettempdir()))
args = parser.parse_args()
args.plasma = args.plasma or args.plasma_fixture
args.work_dir.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='ai-quotas-visual-', dir=args.work_dir) as temporary:
    base = Path(temporary)
    for folder in ['runtime', 'config', 'cache', 'data', 'bin']:
        (base / folder).mkdir(mode=0o700)
    plugin = base / 'data/plasma/plasmoids/org.leoz.aiquotas'
    shutil.copytree(ROOT / 'package', plugin)
    if args.plasma_fixture:
        shutil.copy2(ROOT / 'tests/fixture_collector.py', plugin / 'contents/code/quota_collector.py')
        shutil.copy2(ROOT / 'tests/fixtures/quota-demo.json', plugin / 'contents/code/quota-demo.json')
        # Observe the real native layout without shipping test hooks in the widget.
        main = plugin / 'contents/ui/main.qml'
        source = main.read_text().rstrip()
        main.write_text(source[:-1] + '''
    Timer {
        interval: 100
        running: true
        repeat: true
        onTriggered: {
            const item = root.fullRepresentationItem;
            if (!item || root.loading || !root.report) return;
            console.log("AIQ_TEST_METRICS " + JSON.stringify({
                minimumWidth: item.minimumWidgetWidth,
                minimumHeight: item.minimumWidgetHeight,
                width: item.width, height: item.height
            }));
            stop();
        }
    }
}
''')
    kdeglobals = Path.home() / '.config/kdeglobals'
    if kdeglobals.exists():
        shutil.copy2(kdeglobals, base / 'config/kdeglobals')
    env = dict(os.environ)
    real_runtime = env.get('XDG_RUNTIME_DIR', '/run/user/' + str(os.getuid()))
    real_bus = env.get('DBUS_SESSION_BUS_ADDRESS', 'unix:path=' + real_runtime + '/bus')
    # KIO creates Unix sockets with its own suffix; a long project path exceeds
    # sockaddr_un's path limit. Use a short, private runtime directory.
    runtime_context = tempfile.TemporaryDirectory(prefix='aiq-', dir=real_runtime)
    runtime = runtime_context.name
    (base / 'data/Desktop').mkdir()
    (base / 'config/user-dirs.dirs').write_text('XDG_DESKTOP_DIR="' + str(base / 'data/Desktop') + '"\n')
    # Only the collector's existing wallet CLI calls use the user's wallet bus.
    # The compositor, shell, and test commands use their separate D-Bus session.
    for binary in (['qdbus6', 'kwallet-query'] if args.plasma and not args.plasma_fixture else []):
        wrapper = base / 'bin' / binary
        import shlex
        wrapper.write_text('#!/bin/sh\nexport DBUS_SESSION_BUS_ADDRESS=' + shlex.quote(real_bus)
                           + '\nexport XDG_RUNTIME_DIR=' + shlex.quote(real_runtime)
                           + '\nexport QT_QPA_PLATFORM=offscreen\nexec /usr/bin/' + binary + ' "$@"\n')
        wrapper.chmod(0o700)
    env.update({'XDG_RUNTIME_DIR': runtime, 'XDG_CONFIG_HOME': str(base / 'config'),
                'XDG_CACHE_HOME': str(base / 'cache'), 'XDG_DATA_HOME': str(base / 'data'),
                'QT_QPA_PLATFORM': 'offscreen', 'KWIN_COMPOSE': 'Q', 'QT_QUICK_BACKEND': 'software',
                'QT_QPA_PLATFORMTHEME': 'generic', 'QT_NO_XDG_DESKTOP_PORTAL': '1',
                'QT_FORCE_STDERR_LOGGING': '1',
                'QT_LOGGING_RULES': env.get('QT_LOGGING_RULES', '') + ';qml.debug=true;qml.warning=true;qml.info=true',
                'PATH': str(base / 'bin') + ':/usr/bin:/bin', 'AI_QUOTAS_ISOLATED_TEST': '1'})
    if args.plasma:
        env['KWIN_COMPOSE'] = 'O2'
        env['LIBGL_ALWAYS_SOFTWARE'] = '1'
        env['QSG_RHI_BACKEND'] = 'opengl'
        env.pop('QT_QUICK_BACKEND', None)
    if args.plasma_fixture:
        env['AI_QUOTAS_TEST_FIXTURE'] = '1'
    env.pop('WAYLAND_SOCKET', None)
    child = ROOT / 'tests' / ('validate_plasma.py' if args.plasma else 'validate_ui.py')
    command = ['dbus-run-session', '--', 'kwin_wayland', '--virtual', '--width', '1024',
               '--height', '768', '--output-count', '1', '--socket', 'quota-widget-test',
               '--no-lockscreen', '--no-global-shortcuts', '--no-kactivities',
               '--exit-with-session', 'env QT_QPA_PLATFORM=wayland /usr/bin/python3 ' + str(child)]
    log_path = args.work_dir / ('plasma-validation.log' if args.plasma else 'wayland-validation.log')
    log_file = log_path.open('w')
    process = subprocess.Popen(command, env=env, stdout=log_file, stderr=log_file,
                               text=True, start_new_session=True)
    try:
        process.wait(timeout=60)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        print('Visual validation timed out')
        returncode = 2
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        # D-Bus activation may create a service in a separate process group.
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                settings = (entry / 'environ').read_bytes().split(b'\0')
                if ('XDG_RUNTIME_DIR=' + runtime).encode() in settings:
                    os.kill(int(entry.name), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
        log_file.close()
        lines = log_path.read_text().splitlines()
        print('\n'.join(line for line in lines if line.startswith('VALIDATION:')))
        if returncode:
            print('\n'.join(line for line in lines if any(word in line for word in ['.qml:', 'Error:', 'error:', 'Traceback', 'RuntimeError:']))[-8000:])
        runtime_context.cleanup()
sys.exit(returncode)
