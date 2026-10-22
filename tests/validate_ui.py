import json
import sys
import time
from pathlib import Path
from PySide6.QtCore import QObject, QPoint, QPointF, QTimer, Qt, QUrl, Slot
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick import QQuickView, QQuickWindow
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[1]
(ROOT / 'evidence').mkdir(exist_ok=True)
QQuickWindow.setDefaultAlphaBuffer(True)
app = QGuiApplication(sys.argv)
app.setApplicationName('Cotas de IA — validação')
engine = QQmlEngine()

class Translator(QObject):
    @Slot(str, result=str)
    def translate(self, text):
        return text

translator = Translator()
engine.rootContext().setContextProperty('i18n', engine.newQObject(translator).property('translate'))
view = QQuickView(engine, None)
view.setTitle('Cotas de IA — validação')
view.setResizeMode(QQuickView.SizeRootObjectToView)
view.setColor(QColor('transparent'))
view.resize(300, 180)
view.setSource(QUrl.fromLocalFile(str(ROOT / 'package/contents/ui/FullRepresentation.qml')))
result = {'platform': app.platformName(), 'checks': {}}
if view.status() == QQuickView.Error:
    print(json.dumps({'errors': [e.toString() for e in view.errors()]}))
    sys.exit(1)
root = view.rootObject()
data = json.loads((ROOT / 'tests/fixtures/quota-demo.json').read_text())
root.setProperty('report', engine.toScriptValue(data))
root.setProperty('nowMs', data['generated_at'] * 1000)
root.setProperty('loading', False)
view.show()

def click(item):
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
    QTest.qWait(150)

def find_item(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = find_item(child, name)
        if found:
            return found
    return None

def center(item):
    return item.mapToScene(QPointF(item.width() / 2, item.height() / 2))

def validate():
    try:
        result['screens'] = [{'name': s.name(), 'width': s.geometry().width(), 'height': s.geometry().height()} for s in app.screens()]
        count = []
        root.refreshRequested.connect(lambda: count.append(True))
        view.grabWindow().save(str(ROOT / 'evidence/widget-preview.png'))
        refresh = find_item(root, 'refreshButton')
        click(refresh)
        result['checks']['refresh_button'] = len(count) == 1
        provider = find_item(root, 'provider_codex')
        click(provider)
        result['checks']['provider_detail_expands'] = root.property('expandedId') == 'codex'
        click(provider)
        result['checks']['provider_detail_closes'] = root.property('expandedId') == ''
        QTest.mouseMove(view, QPoint(8, 8))
        QTest.qWait(250)
        result['checks']['screenshot_saved'] = view.grabWindow().save(str(ROOT / 'evidence/widget-preview.png'))
        view.resize(280, 180)
        QTest.qWait(250)
        result['checks']['minimum_size'] = root.width() == 280 and root.height() == 180
        result['checks']['minimum_screenshot_saved'] = view.grabWindow().save(str(ROOT / 'evidence/widget-minimum.png'))
        bars = []
        aligned = []
        icons = []
        ready_icon = engine.evaluate('(function(i) { return i.status === 1 && i.fillMode === 1; })')
        for p in data['providers']:
            icon = find_item(root, 'icon_' + p['id'])
            icons.append(icon is not None and ready_icon.call([engine.newQObject(icon)]).toBool()
                         and icon.height() >= 35)
            for w in p['windows'][:2]:
                suffix = p['id'] + '_' + w['key']
                bar = find_item(root, 'bar_' + suffix)
                reset = find_item(root, 'reset_' + suffix)
                bars.append(bar is not None and bar.width() >= 100
                            and abs(bar.property('value') - w['remaining_percent']) < .01)
                aligned.append(reset is not None and abs(center(bar).y() - center(reset).y()) <= 1)
        result['checks']['remaining_quota_bars'] = len(bars) == 5 and all(bars)
        result['checks']['reset_aligned_with_each_bar'] = all(aligned)
        result['checks']['provider_logos_loaded_preserve_aspect_fill_height'] = all(icons)
        result['checks']['weekly_before_session'] = all(
            center(find_item(root, 'bar_' + p + '_' + weekly)).y()
            < center(find_item(root, 'bar_' + p + '_' + session)).y()
            for p, weekly, session in [('claude', 'seven_day', 'five_hour'), ('ollama', 'weekly', 'session')])
        result['checks']['no_invented_codex_session'] = find_item(root, 'bar_codex_5h') is None
        # Exercise the actual JavaScript formatter at unit boundaries.
        engine.evaluate((ROOT / 'package/contents/ui/lib.js').read_text().replace('.pragma library', ''))
        cases = [(604800, '1w'), (1209600, '2w'), (345600, '4d'),
                 (7200, '2h'), (1800, '30m'), (3599, '59m'), (30, '1m'), (0, '—'), (-1, '—')]
        result['checks']['single_unit_reset_boundaries'] = all(
            engine.evaluate(f'shortCountdown({1000000 + seconds}, 1000000000)').toString() == expected
            for seconds, expected in cases)
        result['checks']['unknown_reset'] = engine.evaluate('shortCountdown(null, 1000000000)').toString() == '—'
        result['checks']['weekly_caption_is_7d'] = all(
            find_item(root, 'bar_' + p + '_' + key + '_caption').property('text') == '7d'
            for p, key in [('codex', '7d'), ('claude', 'seven_day'), ('ollama', 'weekly')])
        result['minimumBarGeometry'] = [
            {'provider': p['id'], 'key': w['key'],
             'centerY': center(find_item(root, 'bar_' + p['id'] + '_' + w['key'])).y(),
             'height': find_item(root, 'bar_' + p['id'] + '_' + w['key']).height(),
             'fontPointSize': find_item(root, 'quota_' + p['id'] + '_' + w['key']).property('font').pointSizeF(),
             'fontPixelSize': find_item(root, 'quota_' + p['id'] + '_' + w['key']).property('font').pixelSize(),
             'trackWidth': find_item(root, 'bar_' + p['id'] + '_' + w['key'] + '_track').width()}
            for p in data['providers'] for w in p['windows'][:2]]
        result['checks']['thin_tracks_not_clipped'] = all(
            find_item(root, 'bar_' + p['id'] + '_' + w['key'] + '_track').width() >= 50
            and center(find_item(root, 'bar_' + p['id'] + '_' + w['key'])).y() + 9 <= root.height() - 10
            for p in data['providers'] for w in p['windows'][:2])
        view.resize(300, 180)
        theme_results = []
        for mode, name in [(1, 'light'), (2, 'dark')]:
            root.setProperty('themeMode', mode)
            QTest.qWait(180)
            picture = view.grabWindow()
            picture.save(str(ROOT / ('evidence/widget-' + name + '.png')))
            alpha = picture.pixelColor(150, 8).alpha()
            ink = root.property('inkColor')
            surface = root.property('surfaceColor')
            icon_origin = refresh.mapToScene(QPointF(5, 5))
            icon_pixels = [picture.pixelColor(round(icon_origin.x()) + x, round(icon_origin.y()) + y).red()
                           for x in range(14) for y in range(14)]
            def lum(rgb):
                values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
                return sum(a * b for a, b in zip(values, [.2126, .7152, .0722]))
            ratios = []
            for backdrop in [0, 1]:
                bg = [c * .82 + backdrop * .18 for c in [surface.redF(), surface.greenF(), surface.blueF()]]
                fg = [c * .75 + b * .25 for c, b in zip([ink.redF(), ink.greenF(), ink.blueF()], bg)]
                ratios.append((max(lum(bg), lum(fg)) + .05) / (min(lum(bg), lum(fg)) + .05))
            theme_results.append({'theme': name, 'surfaceAlpha': alpha,
                                  'transparentCorners': picture.pixelColor(0, 0).alpha() == 0,
                                  'refreshIconVisible': min(icon_pixels) < 120 if mode == 1 else max(icon_pixels) > 150,
                                  'minimumResetTextContrast': min(ratios)})
        result['themes'] = theme_results
        result['checks']['light_and_dark_backgrounds_translucent'] = all(
            abs(t['surfaceAlpha'] - round(.82 * 255)) <= 2 and t['transparentCorners'] for t in theme_results)
        result['checks']['light_dark_text_contrast'] = all(t['minimumResetTextContrast'] >= 4.5 for t in theme_results)
        result['checks']['refresh_icon_visible_in_both_themes'] = all(t['refreshIconVisible'] for t in theme_results)
        root.setProperty('backgroundOpacity', 0)
        QTest.qWait(100)
        result['checks']['background_opacity_can_be_zero'] = view.grabWindow().pixelColor(150, 8).alpha() == 0
        root.setProperty('backgroundOpacity', 100)
        QTest.qWait(100)
        result['checks']['background_opacity_can_be_solid'] = view.grabWindow().pixelColor(150, 8).alpha() == 255
        root.setProperty('backgroundOpacity', 82)
        root.setProperty('themeMode', 0)
        QTest.qWait(100)
        result['checks']['automatic_theme_restores'] = root.property('themeMode') == 0 and root.property('backgroundOpacity') == 82
        zero = json.loads(json.dumps(data))
        zero['providers'][1]['windows'][0]['remaining_percent'] = 0
        root.setProperty('report', engine.toScriptValue(zero))
        QTest.qWait(100)
        result['checks']['zero_quota_is_empty_bar'] = (
            find_item(root, 'bar_claude_five_hour').property('value') == 0
            and find_item(root, 'quota_claude_five_hour').property('text') == '0%')
        expired = json.loads(json.dumps(data))
        for p in expired['providers']:
            if p['id'] == 'claude':
                p['windows'][0]['resets_at'] = data['generated_at'] - 1
        root.setProperty('report', engine.toScriptValue(expired))
        root.setProperty('nowMs', data['generated_at'] * 1000)
        QTest.qWait(150)
        label = find_item(root, 'quota_claude_five_hour')
        result['checks']['expired_window_hidden'] = label is not None and label.property('text') == '—'
        result['checks']['expired_window_has_no_fill_or_reset'] = (
            find_item(root, 'bar_claude_five_hour').property('value') == 0
            and find_item(root, 'reset_claude_five_hour').property('text') == '—')
        root.setProperty('nowMs', (data['generated_at'] + 601) * 1000)
        QTest.qWait(100)
        result['checks']['outdated_provider_bars_hidden'] = find_item(root, 'bar_codex_7d') is None
        root.setProperty('report', engine.toScriptValue(data))
        root.setProperty('nowMs', data['generated_at'] * 1000)
        view.resize(300, 180)
        panel = QQuickView(engine, None)
        panel.setResizeMode(QQuickView.SizeRootObjectToView)
        panel.resize(230, 30)
        panel.setSource(QUrl.fromLocalFile(str(ROOT / 'package/contents/ui/CompactRepresentation.qml')))
        panel_root = panel.rootObject()
        panel_root.setProperty('report', engine.toScriptValue(data))
        panel_root.setProperty('nowMs', data['generated_at'] * 1000)
        panel.show()
        QTest.qWait(200)
        hook = engine.evaluate('(function(item) { var r = {count: 0}; item.clicked.connect(function(){r.count++;}); return r; })')
        counter = hook.call([engine.newQObject(panel_root)])
        QTest.mouseClick(panel, Qt.LeftButton, Qt.NoModifier, QPoint(100, 15))
        QTest.qWait(100)
        result['checks']['panel_click'] = counter.property('count').toInt() == 1
        QTest.keyClick(panel, Qt.Key_Space)
        QTest.qWait(100)
        result['checks']['panel_keyboard'] = counter.property('count').toInt() == 2
        result['checks']['panel_screenshot_saved'] = panel.grabWindow().save(str(ROOT / 'evidence/panel-preview.png'))
        settings = QQuickView(engine, None)
        settings.setResizeMode(QQuickView.SizeRootObjectToView)
        settings.resize(500, 440)
        settings.setSource(QUrl.fromLocalFile(str(ROOT / 'package/contents/ui/config/General.qml')))
        settings_root = settings.rootObject()
        settings_root.setProperty('cfg_showCodex', True)
        settings_root.setProperty('cfg_showClaude', True)
        settings_root.setProperty('cfg_showOllama', True)
        settings_root.setProperty('cfg_refreshIntervalSec', 120)
        settings_root.setProperty('cfg_themeMode', 2)
        settings_root.setProperty('cfg_backgroundOpacity', 82)
        settings.show()
        QTest.qWait(200)
        result['checks']['configuration_loads'] = settings_root.property('cfg_refreshIntervalSec') == 120 and settings_root.property('cfg_showOllama') is True
        result['checks']['appearance_configuration_loads'] = settings_root.property('cfg_themeMode') == 2 and settings_root.property('cfg_backgroundOpacity') == 82
        result['checks']['settings_screenshot_saved'] = settings.grabWindow().save(str(ROOT / 'evidence/settings-preview.png'))
        result['snapshotGeneratedAt'] = data['generated_at']
        result['success'] = all(result['checks'].values())
    except Exception as exc:
        result['success'] = False
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    (ROOT / 'evidence/gui-validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('VALIDATION: ' + json.dumps(result, ensure_ascii=False), flush=True)
    app.exit(0 if result.get('success') else 1)

QTimer.singleShot(1200, validate)
QTimer.singleShot(15000, lambda: app.exit(2))
sys.exit(app.exec())
