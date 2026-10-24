import json
import sys
import time
from pathlib import Path
from PySide6.QtCore import QObject, QPoint, QPointF, QTimer, Qt, QUrl, Slot, QLocale
from PySide6.QtGui import QColor, QGuiApplication, QWheelEvent, QAccessible
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickView, QQuickWindow
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[1]
(ROOT / 'evidence').mkdir(exist_ok=True)
QQuickWindow.setDefaultAlphaBuffer(True)
app = QGuiApplication(sys.argv)
app.setApplicationName('AI Quotes — validation')
engine = QQmlEngine()
# Match the theme backend used by Plasma applet engines.
engine.setProperty("_kirigamiTheme", "Plasma")
qml_warnings = []
engine.warnings.connect(lambda warnings: qml_warnings.extend(w.toString() for w in warnings))

class Translator(QObject):
    @Slot(str, result=str)
    def translate(self, text):
        return text

translator = Translator()
engine.rootContext().setContextProperty('i18n', engine.newQObject(translator).property('translate'))
view = QQuickView(engine, None)
view.setTitle('AI Quotes — validation')
view.setResizeMode(QQuickView.SizeRootObjectToView)
view.setColor(QColor('transparent'))
view.resize(300, 200)
view.setSource(QUrl.fromLocalFile(str(ROOT / 'package/contents/ui/FullRepresentation.qml')))
result = {'platform': app.platformName(), 'checks': {}}
if view.status() == QQuickView.Error:
    print(json.dumps({'errors': [e.toString() for e in view.errors()]}))
    sys.exit(1)
root = view.rootObject()

class ContextMenuHost(QQuickItem):
    """Model the containment receiving presses unhandled by the widget."""
    def __init__(self, window, item):
        super().__init__(window.contentItem())
        self.right_presses = 0
        self.setAcceptedMouseButtons(Qt.RightButton)
        self.setWidth(window.width())
        self.setHeight(window.height())
        window.widthChanged.connect(self.setWidth)
        window.heightChanged.connect(self.setHeight)
        item.setParentItem(self)

    def mousePressEvent(self, event):
        self.right_presses += 1
        event.accept()

context_host = ContextMenuHost(view, root)
data = json.loads((ROOT / 'tests/fixtures/quota-demo.json').read_text())
root.setProperty('report', engine.toScriptValue(data))
root.setProperty('nowMs', data['generated_at'] * 1000)
root.setProperty('loading', False)
view.resize(max(300, round(root.property('minimumWidgetWidth'))), round(root.property('minimumWidgetHeight')))
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
        result['initialMinimumSize'] = [root.property('minimumWidgetWidth'), root.property('minimumWidgetHeight')]
        result['screens'] = [{'name': s.name(), 'width': s.geometry().width(), 'height': s.geometry().height()} for s in app.screens()]
        count = []
        root.refreshRequested.connect(lambda: count.append(True))
        view.grabWindow().save(str(ROOT / 'evidence/widget-preview.png'))
        refresh = find_item(root, 'refreshButton')
        right_click_targets = {'background': QPointF(5, 5), 'header': QPointF(40, 20),
                               'refresh': center(refresh)}
        for provider_id in ['codex', 'claude', 'ollama']:
            for prefix in ['provider_', 'icon_']:
                right_click_targets[prefix + provider_id] = center(find_item(root, prefix + provider_id))
        for name in ['bar_claude_seven_day', 'reset_claude_five_hour']:
            right_click_targets[name] = center(find_item(root, name))
        for name, point in right_click_targets.items():
            before = context_host.right_presses
            QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, point.toPoint())
            result['checks']['right_click_reaches_containment_' + name] = context_host.right_presses == before + 1
        result['checks']['right_click_does_not_refresh_or_expand'] = not count and root.property('expandedId') is None
        click(refresh)
        result['checks']['refresh_button'] = len(count) == 1
        provider = find_item(root, 'provider_codex')
        geometry_before = [(c.objectName(), center(c).y()) for c in [provider, find_item(root, 'provider_claude')]]
        click(provider)
        result['checks']['providers_are_passive_without_expansion'] = root.property('expandedId') is None and geometry_before == [(c.objectName(), center(c).y()) for c in [provider, find_item(root, 'provider_claude')]]
        result['checks']['no_scroll_container'] = find_item(root, 'providerScroll') is None and find_item(root, 'providerScrollBar') is None
        point = center(provider)
        QGuiApplication.sendEvent(view, QWheelEvent(point, view.mapToGlobal(point.toPoint()), QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
        QTest.qWait(100)
        result['checks']['wheel_does_not_move_providers'] = geometry_before == [(c.objectName(), center(c).y()) for c in [provider, find_item(root, 'provider_claude')]]
        title = find_item(root, 'widgetTitle')
        footer = find_item(root, 'footer')
        age = find_item(root, 'lastUpdated')
        result['checks']['footer_refresh_and_age_aligned_right'] = (center(refresh).y() > center(find_item(root, 'provider_ollama')).y() and abs(center(age).y() - center(refresh).y()) < 1 and age.mapToScene(QPointF(age.width(), 0)).x() < refresh.mapToScene(QPointF()).x())
        alignments = []
        root.setProperty('title', 'Custom title')
        for alignment, expected in [(0, Qt.AlignLeft), (1, Qt.AlignHCenter), (2, Qt.AlignRight)]:
            root.setProperty('titleAlignment', alignment)
            QTest.qWait(50)
            alignments.append(engine.evaluate('(function(i) { return i.horizontalAlignment; })').call([engine.newQObject(title)]).toInt() == int(expected) and title.property('text') == 'Custom title')
        result['checks']['title_alignment_left_center_right'] = all(alignments)
        before_height = root.property('minimumWidgetHeight')
        root.setProperty('titleAlignment', 3)
        QTest.qWait(80)
        result['checks']['disabled_title_removes_space_preserves_text'] = not title.isVisible() and root.property('minimumWidgetHeight') < before_height and root.property('title') == 'Custom title'
        before = context_host.right_presses
        QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, QPoint(40, 15))
        result['checks']['right_click_without_title_reaches_containment'] = context_host.right_presses == before + 1
        root.setProperty('titleAlignment', 0)
        root.setProperty('title', '   ')
        result['checks']['blank_title_uses_default'] = title.property('text') == 'AI Quotes'
        long_title = ('Custom title with a complete accessible name ' * 8).strip()
        root.setProperty('title', long_title)
        QTest.qWait(80)
        view.grabWindow()
        title_interface = QAccessible.queryAccessibleInterface(title)
        result['checks']['long_title_elides_without_losing_accessible_text'] = bool(title.property('truncated')) and title_interface.text(QAccessible.Name) == long_title and root.property('minimumWidgetHeight') == before_height
        root.setProperty('title', '')
        error = find_item(root, 'lastError')
        root.setProperty('lastError', 'A detailed query failure message ' * 12)
        QTest.qWait(80)
        view.grabWindow()
        error_interface = QAccessible.queryAccessibleInterface(error)
        result['checks']['long_error_preserves_footer_and_accessible_details'] = bool(error.property('truncated')) and error_interface.text(QAccessible.Description) == root.property('lastError') and age.mapToScene(QPointF(age.width(), 0)).x() < refresh.mapToScene(QPointF()).x() and refresh.mapToScene(QPointF(refresh.width(), 0)).x() <= view.width()
        root.setProperty('lastError', '')
        QTest.mouseMove(view, QPoint(8, 8))
        QTest.qWait(250)
        result['checks']['screenshot_saved'] = view.grabWindow().save(str(ROOT / 'evidence/widget-preview.png'))
        view.resize(round(root.property('minimumWidgetWidth')), round(root.property('minimumWidgetHeight')))
        QTest.qWait(250)
        result['checks']['minimum_size'] = root.width() >= root.property('minimumWidgetWidth') and root.height() >= root.property('minimumWidgetHeight')
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
            find_item(root, 'bar_' + p['id'] + '_' + w['key'] + '_track').width() >= 49
            and center(find_item(root, 'bar_' + p['id'] + '_' + w['key'])).y() + 9 <= root.height() - 10
            for p in data['providers'] for w in p['windows'][:2])
        view.resize(max(300, round(root.property('minimumWidgetWidth'))), round(root.property('minimumWidgetHeight')))
        theme_results = []
        root.forceActiveFocus()
        QTest.mouseMove(view, QPoint(2, 2))
        QTest.qWait(350)
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
            and find_item(root, 'quota_claude_five_hour').property('text') == '0%'
            and find_item(root, 'bar_claude_five_hour_track').opacity() == 1)
        extra = json.loads(json.dumps(data))
        extra['providers'][1]['windows'].append({'key': 'seven_day_sonnet', 'label': 'Sonnet · weekly',
                                                'remaining_percent': 3, 'resets_at': data['generated_at'] + 86400})
        extra['providers'][1]['windows'].append({'key': 'seven_day_opus', 'label': 'Opus · weekly', 'remaining_percent': 30, 'resets_at': data['generated_at'] + 172800})
        root.setProperty('report', engine.toScriptValue(extra))
        QTest.qWait(100)
        engine.globalObject().setProperty('sample', engine.toScriptValue(extra['providers'][1]))
        tooltip = engine.evaluate(f'providerTooltip(sample, {data["generated_at"] * 1000}, 600)').toString()
        result['checks']['two_bars_preserved_and_hidden_critical_window_explained'] = (
            find_item(root, 'bar_claude_seven_day_sonnet') is None
            and find_item(root, 'bar_claude_five_hour') is not None
            and find_item(root, 'bar_claude_seven_day') is not None
            and 'Sonnet · weekly: 3%' in tooltip
            and 'Most restrictive: Sonnet · weekly' in tooltip)
        usd = json.loads(json.dumps(data))
        usd['providers'][2]['windows'] = [{'key': 'purchased', 'label': 'Purchased credits',
                                          'remaining_percent': None, 'remaining_usd': 25, 'resets_at': None}]
        root.setProperty('report', engine.toScriptValue(usd))
        QTest.qWait(100)
        result['checks']['usd_without_percentage_has_value_and_no_empty_rail'] = (
            find_item(root, 'bar_ollama_purchased_track').opacity() == 0
            and find_item(root, 'quota_ollama_purchased').property('text') == 'USD ' + QLocale().toString(25.0, 'f', 2))
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
        result['checks']['provider_icon_stays_active_with_one_live_window'] = find_item(root, 'icon_claude').opacity() == 1
        all_expired = json.loads(json.dumps(data))
        for w in all_expired['providers'][1]['windows']:
            w['resets_at'] = data['generated_at'] + 1
        root.setProperty('report', engine.toScriptValue(all_expired))
        QTest.qWait(50)
        before_opacity = find_item(root, 'icon_claude').opacity()
        root.setProperty('nowMs', (data['generated_at'] + 2) * 1000)
        QTest.qWait(80)
        result['checks']['provider_icon_dims_after_all_windows_expire'] = (
            before_opacity == 1 and find_item(root, 'provider_claude').property('current')
            and abs(find_item(root, 'icon_claude').opacity() - .45) < .001
            and find_item(root, 'quota_claude_five_hour').property('text') == '—'
            and find_item(root, 'quota_claude_seven_day').property('text') == '—')
        hidden_live = json.loads(json.dumps(extra))
        for w in hidden_live['providers'][1]['windows'][:2]:
            w['resets_at'] = data['generated_at'] + 1
        root.setProperty('report', engine.toScriptValue(hidden_live))
        QTest.qWait(50)
        result['checks']['provider_icon_counts_live_windows_outside_the_two_bars'] = (
            find_item(root, 'icon_claude').opacity() == 1
            and find_item(root, 'quota_claude_five_hour').property('text') == '—')
        root.setProperty('nowMs', (data['generated_at'] + 601) * 1000)
        QTest.qWait(100)
        result['checks']['outdated_provider_bars_hidden'] = find_item(root, 'bar_codex_7d') is None
        root.setProperty('report', engine.toScriptValue(data))
        root.setProperty('nowMs', data['generated_at'] * 1000)
        view.resize(max(300, round(root.property('minimumWidgetWidth'))), round(root.property('minimumWidgetHeight')))
        panel = QQuickView(engine, None)
        panel.setResizeMode(QQuickView.SizeRootObjectToView)
        panel.resize(230, 30)
        panel.setSource(QUrl.fromLocalFile(str(ROOT / 'package/contents/ui/CompactRepresentation.qml')))
        panel_root = panel.rootObject()
        panel_context_host = ContextMenuHost(panel, panel_root)
        panel_root.setProperty('report', engine.toScriptValue(data))
        panel_root.setProperty('nowMs', data['generated_at'] * 1000)
        panel.show()
        QTest.qWait(200)
        hook = engine.evaluate('(function(item) { var r = {count: 0}; item.clicked.connect(function(){r.count++;}); return r; })')
        counter = hook.call([engine.newQObject(panel_root)])
        QTest.mouseClick(panel, Qt.RightButton, Qt.NoModifier, QPoint(100, 15))
        result['checks']['panel_right_click_reaches_containment'] = panel_context_host.right_presses == 1
        result['checks']['panel_right_click_does_not_toggle_popup'] = counter.property('count').toInt() == 0
        QTest.mouseClick(panel, Qt.LeftButton, Qt.NoModifier, QPoint(100, 15))
        QTest.qWait(100)
        result['checks']['panel_click'] = counter.property('count').toInt() == 1
        QTest.keyClick(panel, Qt.Key_Space)
        QTest.qWait(100)
        result['checks']['panel_keyboard'] = counter.property('count').toInt() == 2
        result['checks']['panel_uses_distinct_provider_logos'] = all(
            ready_icon.call([engine.newQObject(find_item(panel_root, 'panel_icon_' + p['id']))]).toBool()
            for p in data['providers'])
        description = panel_root.property('quotaDescription')
        result['checks']['panel_accessibility_contains_provider_names_and_quotas'] = all(
            label in description for label in ['Codex: Weekly 72%', 'Claude: 5h 61%', 'Ollama Cloud: Weekly ' + QLocale().toString(35.2, 'f', 1) + '%'])
        result['checks']['panel_screenshot_saved'] = panel.grabWindow().save(str(ROOT / 'evidence/panel-preview.png'))
        settings = QQuickView(engine, None)
        settings.setResizeMode(QQuickView.SizeRootObjectToView)
        settings.resize(540, 600)
        settings.setSource(QUrl.fromLocalFile(str(ROOT / 'package/contents/ui/config/General.qml')))
        settings_root = settings.rootObject()
        settings_root.setProperty('cfg_title', 'My AI tools')
        settings_root.setProperty('cfg_titleAlignment', 2)
        settings_root.setProperty('cfg_bodyFontSize', 8)
        visibility_keys = ['showProviderIcon', 'showQuotaPeriod', 'showProgressBar', 'showQuotaValue', 'showResetTime']
        for key in visibility_keys:
            settings_root.setProperty('cfg_' + key, True)
        settings_root.setProperty('cfg_showCodex', True)
        settings_root.setProperty('cfg_showClaude', True)
        settings_root.setProperty('cfg_showOllama', True)
        settings_root.setProperty('cfg_refreshIntervalSec', 120)
        settings_root.setProperty('cfg_themeMode', 2)
        settings_root.setProperty('cfg_backgroundOpacity', 82)
        settings.show()
        QTest.qWait(200)
        result['checks']['title_configuration_loads'] = settings_root.property('cfg_title') == 'My AI tools' and settings_root.property('cfg_titleAlignment') == 2
        result['checks']['font_size_configuration_loads'] = settings_root.property('cfg_bodyFontSize') == 8
        result['checks']['card_element_configuration_loads'] = all(settings_root.property('cfg_' + key) is True for key in visibility_keys)
        result['checks']['configuration_loads'] = settings_root.property('cfg_refreshIntervalSec') == 120 and settings_root.property('cfg_showOllama') is True
        result['checks']['appearance_configuration_loads'] = settings_root.property('cfg_themeMode') == 2 and settings_root.property('cfg_backgroundOpacity') == 82
        result['checks']['settings_screenshot_saved'] = settings.grabWindow().save(str(ROOT / 'evidence/settings-preview.png'))
        # Real phase test: the first tick must occur at the data's minute,
        # not one minute after the widget/report happened to load.
        QAccessible.setActive(True)
        engine.evaluate((ROOT / 'package/contents/ui/lib.js').read_text().replace('.pragma library', ''))
        now_epoch = time.time()
        timed = json.loads(json.dumps(data))
        for p in timed['providers']:
            p['fetched_at'] = now_epoch - 59.1
        root.setProperty('report', engine.toScriptValue(timed))
        timer = root.findChild(QObject, 'ageTimer')
        result['checks']['age_timer_first_tick_aligned_to_data'] = age.property('text') == 'Now' and 1 <= timer.property('interval') <= 1000
        QTest.qWait(1100)
        result['checks']['age_real_timer_crosses_minute_boundary'] = age.property('text') == '1m' and timer.property('interval') > 58000
        age_clock = root.property('ageNowMs')
        root.setProperty('nowMs', root.property('nowMs') + 5000)
        result['checks']['normal_quota_tick_does_not_recalculate_age'] = root.property('ageNowMs') == age_clock
        before_text = age.property('text')
        root.setProperty('nowMs', (data['generated_at'] + 900) * 1000)
        result['checks']['age_independent_of_five_second_quota_clock'] = age.property('text') == before_text
        root.setVisible(False)
        result['checks']['age_timer_stops_when_hidden'] = not timer.property('running')
        root.setProperty('report', engine.toScriptValue(timed))
        root.setVisible(True)
        result['checks']['age_timer_rearms_when_visible'] = timer.property('running') and age.property('text') == '1m'
        cached = json.loads(json.dumps(timed))
        cached['generated_at'] = time.time()
        cached['providers'][1]['fetched_at'] = time.time() - 541
        cached['providers'][1]['state'] = 'stale'
        root.setProperty('report', engine.toScriptValue(cached))
        result['checks']['partial_cache_does_not_rejuvenate_footer'] = age.property('text') == '9m'
        root.setProperty('lastError', 'Failed query; keeping previous data')
        result['checks']['failed_query_does_not_reset_footer'] = age.property('text') == '9m'
        root.setProperty('lastError', '')
        empty = json.loads(json.dumps(data)); empty['providers'] = []
        root.setProperty('report', engine.toScriptValue(empty))
        result['checks']['empty_report_has_no_invented_age'] = age.property('text') == '—' and not timer.property('running')
        boundaries = [(59.9, 'Now'), (60, '1m'), (120, '2m'), (3599, '59m'), (3600, '1h'), (86400, '1d'), (604800, '1w'), (-30, 'Now')]
        result['checks']['age_single_unit_boundaries'] = all(engine.evaluate(f'shortAge(1000000, {(1000000 + seconds) * 1000})').toString() == expected for seconds, expected in boundaries)
        result['checks']['age_invalid_timestamp_is_unknown'] = all(engine.evaluate(f'shortAge({epoch}, 1000000000)').toString() == '—' for epoch in ['null', 'true', 'NaN', '-1', '0', 'Infinity'])
        result['checks']['age_phase_and_delayed_resume'] = (engine.evaluate('nextAgeInterval(1000000, 1000059900)').toInt() == 100 and engine.evaluate('nextAgeInterval(1000000, 1000180500)').toInt() == 59500)
        root.setProperty('report', engine.toScriptValue(extra))
        root.setProperty('nowMs', data['generated_at'] * 1000)
        view.resize(max(300, round(root.property('minimumWidgetWidth'))), round(root.property('minimumWidgetHeight')))
        QTest.qWait(100)
        view.grabWindow()
        provider = find_item(root, 'provider_claude')
        view.requestActivate()
        QTest.qWait(150)
        tooltip_events = []
        provider.toolTipVisibleChanged.connect(lambda shown: tooltip_events.append(shown))
        provider.forceActiveFocus()
        QTest.qWait(900)
        details = provider.property('tooltipText')
        result['checks']['tooltip_keeps_all_windows_source_and_collection_age'] = all(t in details for t in ['Available', '5h', '7d', 'Sonnet · weekly: 3%', 'Opus · weekly: 30%', 'Most restrictive: Sonnet · weekly', 'Demo — sample data', 'Updated now', 'Resets in'])
        result['checks']['tooltip_visible_on_keyboard_focus'] = any(tooltip_events) and provider.hasActiveFocus()
        interface = QAccessible.queryAccessibleInterface(provider)
        result['checks']['provider_accessible_description_contains_full_details'] = interface is not None and interface.text(QAccessible.Description) == details
        result['visibleWindows'] = [{'title': w.title(), 'class': w.metaObject().className(), 'type': int(w.type()), 'visible': w.isVisible(), 'width': w.width(), 'height': w.height()} for w in app.topLevelWindows()]
        tooltip_windows = [w for w in app.topLevelWindows() if w.isVisible() and w.metaObject().className().endswith('ToolTipDialog')]
        def text_items(item):
            found = [item] if item.property('text') == details else []
            for child in item.childItems(): found.extend(text_items(child))
            return found
        tooltip_labels = [item for w in tooltip_windows for item in text_items(w.contentItem())]
        result['tooltipGeometry'] = [{'width': w.width(), 'height': w.height()} for w in tooltip_windows]
        result['tooltipLabels'] = [{'height': i.height(), 'contentHeight': i.property('contentHeight'), 'truncated': i.property('truncated')} for i in tooltip_labels]
        result['checks']['compact_tooltip_uses_separate_native_window'] = bool(tooltip_windows) and all(w is not view for w in tooltip_windows) and len(details.splitlines()) <= 7
        result['checks']['native_tooltip_full_content_not_clipped'] = bool(tooltip_labels) and all(not i.property('truncated') and i.height() >= i.property('contentHeight') - 1 for i in tooltip_labels)
        tooltip_contrasts = []
        for w in tooltip_windows:
            picture = w.grabWindow()
            picture.save(str(ROOT / 'evidence/widget-tooltip.png'))
            background = picture.pixelColor(picture.width() - 12, picture.height() - 12)
            for label in text_items(w.contentItem()):
                foreground = label.property('color')
                a = lum([background.redF(), background.greenF(), background.blueF()])
                b = lum([foreground.redF(), foreground.greenF(), foreground.blueF()])
                tooltip_contrasts.append((max(a, b) + .05) / (min(a, b) + .05))
        result['tooltipContrast'] = tooltip_contrasts
        result['checks']['native_tooltip_text_has_readable_contrast'] = bool(tooltip_contrasts) and min(tooltip_contrasts) >= 4.5
        before = context_host.right_presses
        QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, center(provider).toPoint())
        result['checks']['right_click_with_tooltip_reaches_containment'] = context_host.right_presses == before + 1
        root.forceActiveFocus()
        QTest.mouseMove(view, QPoint(2, 2))
        QTest.qWait(250)
        tooltip_events.clear()
        QTest.mouseMove(view, center(provider).toPoint())
        QTest.qWait(900)
        result['checks']['tooltip_visible_on_hover'] = provider.property('containsMouse') and any(tooltip_events)
        refresh.forceActiveFocus()
        QTest.qWait(100)
        before_count = len(count)
        QTest.keyClick(view, Qt.Key_Space)
        result['checks']['desktop_refresh_keyboard'] = len(count) == before_count + 1
        root.setProperty('loading', True)
        click(refresh)
        result['checks']['refresh_disabled_during_collection'] = len(count) == before_count + 1
        root.setProperty('loading', False)
        root.forceActiveFocus()
        QTest.mouseMove(view, QPoint(2, 2))
        # Different provider counts/aspect ratios exercise actual layouts and fonts.
        base_font_size = root.property('bodyFontSize')
        title_font = title.property('font')
        matrix = []
        for font_size in [6, 8, 18, 24]:
            root.setProperty('bodyFontSize', font_size)
            for provider_count in [0, 1, 2, 3]:
                sample = json.loads(json.dumps(data)); sample['providers'] = sample['providers'][:provider_count]
                root.setProperty('report', engine.toScriptValue(sample))
                QTest.qWait(40)
                for alignment in [0, 3]:
                    root.setProperty('titleAlignment', alignment)
                    QTest.qWait(40)
                    for shape in ['minimum', 'wide', 'tall']:
                        min_width = round(root.property('minimumWidgetWidth')); min_height = round(root.property('minimumWidgetHeight'))
                        view.resize(min_width * (2 if shape == 'wide' else 1), min_height * (2 if shape == 'tall' else 1))
                        QTest.qWait(60)
                        view.grabWindow()  # Flush layout polish even when another test window obscures it.
                        good = root.property('labelFont').pointSizeF() == font_size and title.property('font') == title_font
                        problems = []
                        for p in sample['providers']:
                            icon = find_item(root, 'icon_' + p['id'])
                            good &= abs(icon.width() - icon.height()) < 1
                            for w in p['windows'][:2]:
                                suffix = p['id'] + '_' + w['key']
                                rail = find_item(root, 'bar_' + suffix + '_track')
                                reset = find_item(root, 'reset_' + suffix)
                                value = find_item(root, 'quota_' + suffix)
                                good &= rail.width() >= 49 and value.width() + 1 >= value.property('contentWidth')
                                good &= center(reset).y() + reset.height() / 2 <= footer.mapToScene(QPointF()).y() + 1
                                if not good:
                                    problems.append({'railWidth': rail.width(), 'valueWidth': value.width(), 'textWidth': value.property('contentWidth'), 'valueHeight': value.height(), 'resetHeight': reset.height(), 'baseLine': root.property('baseLineHeight'), 'baseRow': root.property('baseRowHeight'), 'resetBottom': center(reset).y() + reset.height() / 2, 'footerTop': footer.mapToScene(QPointF()).y(), 'icon': [icon.width(), icon.height()]})
                        matrix.append({'providers': provider_count, 'alignment': alignment, 'font': font_size, 'shape': shape, 'size': [view.width(), view.height()], 'pass': bool(good), 'problems': problems})
        result['layoutMatrix'] = matrix
        result['checks']['responsive_layout_provider_counts_fonts_and_aspect_ratios'] = all(row['pass'] for row in matrix)
        root.setProperty('bodyFontSize', base_font_size)
        root.setProperty('titleAlignment', 0)
        root.setProperty('report', engine.toScriptValue(data))
        # Every combination must collapse hidden columns and retain full details.
        visibility_matrix = []
        for font_size in [8, 24]:
            root.setProperty('bodyFontSize', font_size)
            for mask in range(32):
                flags = {key: bool(mask & (1 << bit)) for bit, key in enumerate(visibility_keys)}
                for key, enabled in flags.items():
                    root.setProperty(key, enabled)
                QTest.qWait(25)
                view.resize(round(root.property('minimumWidgetWidth')), round(root.property('minimumWidgetHeight')))
                QTest.qWait(40)
                view.grabWindow()
                good = True
                for p in data['providers']:
                    icon = find_item(root, 'icon_' + p['id'])
                    good &= icon.isVisible() == flags['showProviderIcon']
                    for w in p['windows'][:2]:
                        suffix = p['id'] + '_' + w['key']
                        bar = find_item(root, 'bar_' + suffix)
                        caption = find_item(root, 'bar_' + suffix + '_caption')
                        rail = find_item(root, 'bar_' + suffix + '_track')
                        value = find_item(root, 'quota_' + suffix)
                        reset = find_item(root, 'reset_' + suffix)
                        for item, key in [(caption, 'showQuotaPeriod'), (rail, 'showProgressBar'), (value, 'showQuotaValue'), (reset, 'showResetTime')]:
                            good &= item.isVisible() == flags[key]
                            if item.isVisible():
                                good &= item.mapToScene(QPointF()).x() >= root.property('padding') - 1
                                good &= item.mapToScene(QPointF(item.width(), 0)).x() <= view.width() - root.property('padding') + 1
                        if rail.isVisible(): good &= rail.width() >= 49
                        if value.isVisible(): good &= value.width() + 1 >= value.property('contentWidth')
                        if not flags['showProviderIcon'] and bar.isVisible():
                            good &= abs(bar.mapToScene(QPointF()).x() - root.property('padding')) <= 1
                    good &= p['label'] in find_item(root, 'provider_' + p['id']).property('tooltipText')
                diagnostics = []
                if not good:
                    for key in ['bar_claude_seven_day_caption', 'bar_claude_seven_day_track', 'quota_claude_seven_day', 'reset_claude_seven_day']:
                        item = find_item(root, key)
                        diagnostics.append({'item': key, 'visible': item.isVisible(), 'x': item.mapToScene(QPointF()).x(), 'width': item.width(), 'contentWidth': item.property('contentWidth')})
                visibility_matrix.append({'font': font_size, 'flags': flags, 'pass': bool(good), 'size': [view.width(), view.height()], 'scale': root.property('uiScale'), 'problems': diagnostics})
        result['visibilityMatrix'] = visibility_matrix
        result['checks']['all_card_element_combinations_fit_and_reclaim_space'] = all(row['pass'] for row in visibility_matrix)
        provider = find_item(root, 'provider_claude')
        for key in visibility_keys: root.setProperty(key, False)
        QTest.qWait(60)
        before = context_host.right_presses
        QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, center(provider).toPoint())
        result['checks']['right_click_with_all_card_elements_hidden'] = context_host.right_presses == before + 1
        result['checks']['hidden_card_elements_keep_full_accessible_details'] = QAccessible.queryAccessibleInterface(provider).text(QAccessible.Description) == provider.property('tooltipText')
        for key in visibility_keys: root.setProperty(key, True)
        # Countdown boundaries and expiry must not change geometry without a report.
        root.setProperty('bodyFontSize', 24)
        def clock_geometry():
            return {key: root.property(key) for key in ['minimumWidgetWidth', 'minimumWidgetHeight', 'uiScale', 'baseResetWidth', 'baseValueWidth']}
        boundary_results = []
        for seconds, initial, following in [(36001, '10h', '9h'), (604801, '1w', '6d'), (601, '10m', '9m')]:
            sample = json.loads(json.dumps(data))
            for p in sample['providers']:
                for w in p['windows']: w['resets_at'] = data['generated_at'] + seconds
            root.setProperty('nowMs', data['generated_at'] * 1000)
            root.setProperty('report', engine.toScriptValue(sample))
            view.resize(max(500, round(root.property('minimumWidgetWidth'))), max(400, round(root.property('minimumWidgetHeight'))))
            QTest.qWait(80); view.grabWindow()
            before = clock_geometry()
            initial_text = find_item(root, 'reset_claude_five_hour').property('text')
            root.setProperty('nowMs', (data['generated_at'] + 2) * 1000)
            QTest.qWait(80); view.grabWindow()
            after = clock_geometry()
            final_text = find_item(root, 'reset_claude_five_hour').property('text')
            boundary_results.append({'from': initial_text, 'to': final_text, 'before': before, 'after': after,
                                     'pass': initial_text == initial and final_text == following and before == after})
        result['clockBoundaryGeometry'] = boundary_results
        result['checks']['countdown_boundaries_keep_minimum_width_and_scale'] = all(row['pass'] for row in boundary_results)
        usd_expiry = json.loads(json.dumps(data))
        usd_expiry['providers'][2]['windows'] = [{'key': 'monthly', 'label': 'Monthly', 'remaining_percent': None,
                                                 'remaining_usd': 12345.67, 'resets_at': data['generated_at'] + 1}]
        root.setProperty('nowMs', data['generated_at'] * 1000)
        root.setProperty('report', engine.toScriptValue(usd_expiry))
        view.resize(max(500, round(root.property('minimumWidgetWidth'))), max(400, round(root.property('minimumWidgetHeight'))))
        QTest.qWait(80); view.grabWindow()
        before = clock_geometry()
        initial_text = find_item(root, 'quota_ollama_monthly').property('text')
        root.setProperty('nowMs', (data['generated_at'] + 2) * 1000)
        QTest.qWait(80); view.grabWindow()
        after = clock_geometry()
        result['usdExpiryGeometry'] = {'before': before, 'after': after}
        result['checks']['usd_expiry_hides_value_without_shrinking_columns'] = (
            initial_text == 'USD ' + QLocale().toString(12345.67, 'f', 2)
            and find_item(root, 'quota_ollama_monthly').property('text') == '—' and before == after)
        root.setProperty('report', engine.toScriptValue(data))
        root.setProperty('nowMs', data['generated_at'] * 1000)
        root.setProperty('bodyFontSize', base_font_size)
        view.resize(max(300, round(root.property('minimumWidgetWidth'))), round(root.property('minimumWidgetHeight')))
        QTest.qWait(150)
        result['qmlWarnings'] = [w for w in qml_warnings if str(ROOT / 'package') in w]
        result['checks']['no_widget_qml_warnings'] = not result['qmlWarnings']
        result['snapshotGeneratedAt'] = data['generated_at']
        result['success'] = all(result['checks'].values())
    except Exception as exc:
        result['success'] = False
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    (ROOT / 'evidence/gui-validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('VALIDATION: ' + json.dumps(result, ensure_ascii=False), flush=True)
    app.exit(0 if result.get('success') else 1)

QTimer.singleShot(1200, validate)
QTimer.singleShot(50000, lambda: app.exit(2))
sys.exit(app.exec())
