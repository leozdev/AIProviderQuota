"""Load the actual plasmoid in a private Plasma/Wayland session and collect live data."""
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
log_path = Path(os.environ['XDG_CACHE_HOME']) / 'plasmashell.log'

def bus(service, object_path, method, *args):
    p = subprocess.run(['/usr/bin/qdbus6', service, object_path, method, *args],
                       capture_output=True, text=True, timeout=12)
    if p.returncode:
        raise RuntimeError('D-Bus call failed: ' + method)
    return p.stdout.strip()

def script(code):
    return bus('org.kde.plasmashell', '/PlasmaShell', 'org.kde.PlasmaShell.evaluateScript', code)

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
        cache = Path(os.environ['XDG_CACHE_HOME']) / 'ai-quotas'
        deadline = time.monotonic() + 20
        snapshots = {}
        cached = {}
        while time.monotonic() < deadline:
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
        result['checks']['executable_engine_finished_all_providers'] = len(cached) == 3
        result['liveSourcesAllAvailable'] = bool(snapshots) and all(
            row and row.get('state') == 'ok' for row in snapshots.values())
        result['liveSourceStates'] = {
            pid: (row['state'] if row else 'rate_limited' if cached[pid].get('next_allowed_at', 0) > time.time() else 'unavailable')
            for pid, row in snapshots.items()}
        print('VALIDATION: collector states ' + json.dumps({p: r.get('state') if r else None for p, r in snapshots.items()}), flush=True)
        (ROOT / 'evidence/plasma-live-sources.json').write_text(json.dumps(snapshots, ensure_ascii=False, indent=2) + '\n')
        geometry = json.loads(script('var g=desktopById(%d).widgetById(%d).geometry;print(JSON.stringify({x:g.x,y:g.y,width:g.width,height:g.height}));' % (desktop, widget_id)))
        result['geometry'] = geometry
        result['checks']['full_representation_has_usable_size'] = geometry['width'] >= 280 and geometry['height'] >= 180
        image_path = Path(os.environ['XDG_CACHE_HOME']) / 'desktop.png'
        bus('org.kde.KWin', '/KWin', 'org.kde.KWin.showDesktop', 'true')
        time.sleep(0.3)
        capture = subprocess.run(['/usr/bin/spectacle', '--background', '--nonotify', '--fullscreen',
                                  '--output', str(image_path)], capture_output=True, text=True, timeout=12)
        print('VALIDATION: screenshot result ' + str(capture.returncode) + ', file=' + str(image_path.exists()), flush=True)
        margin = 8
        if capture.returncode == 0 and image_path.exists():
            image = Image.open(image_path)
            image.save(ROOT / 'evidence/plasma-desktop.png')
            x, y = max(0, int(geometry['x']) - margin), max(0, int(geometry['y']) - margin)
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
        (ROOT / 'evidence/plasma-live-sources.json').write_text(json.dumps(snapshots, ensure_ascii=False, indent=2) + '\n')
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
