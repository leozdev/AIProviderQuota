"""Load the actual plasmoid in a private Plasma/Wayland session."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from PIL import Image

if os.environ.get('AI_QUOTAS_ISOLATED_TEST') != '1':
    raise SystemExit('Run through run_wayland_validation.py --plasma')
ROOT = Path(__file__).resolve().parents[1]
result = {'environment': 'isolated Plasma shell on KWin Wayland Virtual-0', 'checks': {}}
fixture = os.environ.get('AI_QUOTAS_TEST_FIXTURE') == '1'
result['dataSource'] = 'synthetic fixture' if fixture else 'live accounts'
log_path = Path(os.environ['XDG_CACHE_HOME']) / 'plasmashell.log'

def bus(service, object_path, method, *args):
    p = subprocess.run(['/usr/bin/qdbus6', service, object_path, method, *args],
                       capture_output=True, text=True, timeout=12)
    if p.returncode:
        raise RuntimeError('D-Bus call failed: ' + method)
    return p.stdout.strip()

def script(code):
    return bus('org.kde.plasmashell', '/PlasmaShell', 'org.kde.PlasmaShell.evaluateScript', code)

def wait_records(name, count):
    path = Path(os.environ['XDG_CACHE_HOME']) / ('fixture-' + name + '.jsonl')
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        try:
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            if len(rows) >= count:
                return rows
        except (OSError, ValueError):
            pass
        time.sleep(.05)
    raise RuntimeError('Timed out waiting for fixture ' + name)

with log_path.open('w') as log:
    shell = subprocess.Popen(['/usr/bin/plasmashell', '--no-respawn'], stdout=log, stderr=log)
    try:
        print('VALIDATION: starting private Plasma shell', flush=True)
        deadline = time.monotonic() + 12
        desktop = None
        while time.monotonic() < deadline:
            try:
                rows = json.loads(script('print(JSON.stringify(desktops().map(function(d){return {id:d.id,screen:d.screen};})));'))
                if rows:
                    desktop = rows[0]['id']
                    break
            except (RuntimeError, ValueError):
                pass
            time.sleep(0.2)
        if desktop is None:
            raise RuntimeError('Private Plasma desktop did not become ready')
        print('VALIDATION: desktop ready ' + str(desktop), flush=True)
        widget_id = int(script('var d=desktopById(%d);var w=d.addWidget("org.leoz.aiquotas");print(w.id);' % desktop))
        print('VALIDATION: widget created ' + str(widget_id), flush=True)
        result['widgetId'] = widget_id
        if fixture:
            wait_records('requests', 1)
            config = 'var w=desktopById(%d).widgetById(%d);w.currentConfigGroup=["General"];' % (desktop, widget_id)
            script(config + 'w.writeConfig("showClaude",false);')
            requests = wait_records('requests', 2)
            wait_records('completions', 2)
            result['checks']['configuration_changed_during_query_is_collected_immediately'] = requests[:2] == [
                ['codex', 'claude', 'ollama'], ['codex', 'ollama']]
            script(config + 'w.writeConfig("showClaude",true);')
            wait_records('completions', 3)
            time.sleep(.3)
            result['checks']['no_duplicate_initial_or_configuration_queries'] = len(wait_records('requests', 3)) == 3
            result['fixtureRequests'] = wait_records('requests', 3)
            script(config + 'w.writeConfig("title","My AI tools");w.writeConfig("titleAlignment",2);')
            saved = json.loads(script(config + 'print(JSON.stringify({title:w.readConfig("title"),alignment:w.readConfig("titleAlignment")}));'))
            result['checks']['native_title_and_alignment_config_roundtrip'] = saved['title'] == 'My AI tools' and str(saved['alignment']) == '2'
            script(config + 'w.writeConfig("bodyFontSize",10);')
            result['checks']['native_font_size_config_roundtrip'] = int(script(config + 'print(w.readConfig("bodyFontSize"));')) == 10
            script(config + 'w.writeConfig("bodyFontSize",8);')
            script(config + 'w.writeConfig("title","");w.writeConfig("titleAlignment",0);')
            visibility_keys = ['showProviderIcon', 'showQuotaPeriod', 'showProgressBar', 'showQuotaValue', 'showResetTime']
            script(config + ''.join('w.writeConfig("' + key + '",false);' for key in visibility_keys))
            saved = json.loads(script(config + 'print(JSON.stringify([' + ','.join('w.readConfig("' + key + '")' for key in visibility_keys) + ']));'))
            result['nativeCardElements'] = dict(zip(visibility_keys, saved))
            # Plasma's scripting API can serialize readConfig booleans as text.
            result['checks']['native_card_elements_config_roundtrip'] = len(saved) == 5 and all(value is False or value == 'false' for value in saved)
            script(config + ''.join('w.writeConfig("' + key + '",true);' for key in visibility_keys))
            result['checks']['appearance_changes_do_not_query_providers'] = len(wait_records('requests', 3)) == 3
        cache = Path(os.environ['XDG_CACHE_HOME']) / 'ai-quotas'
        deadline = time.monotonic() + 20
        snapshots = {}
        cached = {}
        while not fixture and time.monotonic() < deadline:
            try:
                cached = {pid: json.loads((cache / (pid + '.json')).read_text())
                          for pid in ['codex', 'claude', 'ollama']}
                snapshots = {pid: row.get('snapshot') for pid, row in cached.items()}
                break
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.25)
        # UI integration must complete even when a remote provider limits queries.
        # Report live availability separately; never turn that state into an OK quota.
        if not fixture:
            result['checks']['executable_engine_finished_all_providers'] = len(cached) == 3
            result['liveSourcesAllAvailable'] = bool(snapshots) and all(
                row and row.get('state') == 'ok' for row in snapshots.values())
            result['liveSourceStates'] = {
                pid: (row['state'] if row else 'rate_limited' if cached[pid].get('next_allowed_at', 0) > time.time() else 'unavailable')
                for pid, row in snapshots.items()}
            (ROOT / 'evidence/plasma-live-sources.json').write_text(json.dumps(snapshots, ensure_ascii=False, indent=2) + '\n')
        geometry = json.loads(script('var g=desktopById(%d).widgetById(%d).geometry;print(JSON.stringify({x:g.x,y:g.y,width:g.width,height:g.height}));' % (desktop, widget_id)))
        result['geometry'] = geometry
        if fixture:
            metrics = [json.loads(line.split('AIQ_TEST_METRICS ', 1)[1]) for line in log_path.read_text().splitlines() if 'AIQ_TEST_METRICS ' in line]
            result['nativeLayout'] = metrics[-1] if metrics else {}
            result['checks']['full_representation_has_usable_size'] = bool(metrics) and metrics[-1]['width'] >= metrics[-1]['minimumWidth'] and metrics[-1]['height'] >= metrics[-1]['minimumHeight']
        else:
            result['checks']['full_representation_has_usable_size'] = geometry['width'] > 0 and geometry['height'] > 0
        image_path = Path(os.environ['XDG_CACHE_HOME']) / 'desktop.png'
        bus('org.kde.KWin', '/KWin', 'org.kde.KWin.showDesktop', 'true')
        time.sleep(0.3)
        capture = subprocess.run(['/usr/bin/spectacle', '--background', '--nonotify', '--fullscreen',
                                  '--output', str(image_path)], capture_output=True, text=True, timeout=12)
        print('VALIDATION: screenshot result ' + str(capture.returncode) + ', file=' + str(image_path.exists()), flush=True)
        margin = 8
        x, y = max(0, int(geometry['x']) - margin), max(0, int(geometry['y']) - margin)
        if capture.returncode == 0 and image_path.exists():
            image = Image.open(image_path)
            image.save(ROOT / 'evidence/plasma-desktop.png')
            cropped = image.crop((x, y, x + int(geometry['width']) + margin * 2, y + int(geometry['height']) + margin * 2))
            cropped.save(ROOT / 'evidence/plasma-widget.png')
            result['checks']['native_plasma_screenshot'] = True
        else:
            result['checks']['native_plasma_screenshot'] = False
        theme_images = []
        for mode, name in [(1, 'light'), (2, 'dark')]:
            script('var w=desktopById(%d).widgetById(%d);w.currentConfigGroup=["General"];w.writeConfig("themeMode",%d);w.writeConfig("backgroundOpacity",82);' % (desktop, widget_id, mode))
            time.sleep(.35)
            capture = subprocess.run(['/usr/bin/spectacle', '--background', '--nonotify', '--fullscreen',
                                      '--output', str(image_path)], capture_output=True, text=True, timeout=12)
            if capture.returncode == 0:
                image = Image.open(image_path)
                image.crop((x, y, x + int(geometry['width']) + margin * 2, y + int(geometry['height']) + margin * 2)).save(ROOT / ('evidence/plasma-widget-' + name + '.png'))
                theme_images.append(name)
        result['checks']['native_light_and_dark_screenshots'] = theme_images == ['light', 'dark']
        log.flush()
        log_text = log_path.read_text()
        errors = [line for line in log_text.splitlines() if 'org.leoz.aiquotas' in line
                  and any(token in line for token in ['TypeError:', 'ReferenceError:', 'is not a type', 'Cannot assign', 'Unable to assign', 'Binding loop'])]
        result['checks']['no_widget_qml_errors'] = not errors
        result['qmlErrors'] = errors
        result['success'] = all(result['checks'].values())
    except Exception as exc:
        result['success'] = False
        result['error'] = str(exc)
    finally:
        # Exit the compositor session first; the parent runner owns all process
        # cleanup. This avoids tearing down the shell underneath a rendering job.
        log.flush()
        (ROOT / 'evidence/plasma-shell.log').write_text(log_path.read_text())
result['checkedAt'] = time.time()
(ROOT / 'evidence/plasma-validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print('VALIDATION: ' + json.dumps(result, ensure_ascii=False), flush=True)
sys.exit(0 if result.get('success') else 1)
