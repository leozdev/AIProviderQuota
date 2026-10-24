pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import org.kde.plasma.components as PC
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami as Kirigami
import "lib.js" as Lib

// A passive container lets Plasma receive right presses for its context menu.
PC.Control {
    id: full
    property var report: null
    property bool loading: false
    property string lastError: ""
    property double nowMs: Date.now()
    property int maxAge: 600
    property string title: ""
    property int titleAlignment: 0
    property int bodyFontSize: 8
    property bool showProviderIcon: true
    property bool showQuotaPeriod: true
    property bool showProgressBar: true
    property bool showQuotaValue: true
    property bool showResetTime: true
    property int themeMode: 0
    property int backgroundOpacity: 82
    readonly property string effectiveTitle: title.trim() || i18n("AI Quotes")
    readonly property bool showTitle: titleAlignment !== 3
    readonly property color surfaceColor: themeMode === 1 ? "#f8fafc" : themeMode === 2 ? "#171c25" : Kirigami.Theme.backgroundColor
    readonly property color inkColor: themeMode === 1 ? "#17212d" : themeMode === 2 ? "#f1f5f9" : Kirigami.Theme.textColor
    readonly property color negativeColor: themeMode === 1 ? "#c02832" : themeMode === 2 ? "#ff7b86" : Kirigami.Theme.negativeTextColor
    property font labelFont: {
        const bodyFont = Lib.scaledFont(Kirigami.Theme.smallFont, 1);
        bodyFont.pointSize = full.bodyFontSize;
        return bodyFont;
    }
    readonly property font scaledLabelFont: Lib.scaledFont(labelFont, uiScale)
    readonly property int providerCount: report ? report.providers.length : 3
    readonly property real baseLineHeight: Math.ceil(baseLabel.implicitHeight)
    readonly property real baseRowHeight: Math.max(36, Math.max(16, baseLineHeight) * 2 + 4)
    readonly property real baseCaptionWidth: Math.max(26, textWidth("Extra"))
    readonly property real baseValueWidth: measuredValueWidth()
    // Reserve two digits per countdown unit; clock ticks must not resize columns.
    readonly property real baseResetWidth: Math.ceil(Math.max(26, textWidth("99w"), textWidth("99d"), textWidth("99h"), textWidth("99m")))
    readonly property int quotaColumnCount: Number(showQuotaPeriod) + Number(showProgressBar) + Number(showQuotaValue) + Number(showResetTime)
    readonly property real minimumWidgetWidth: Math.ceil(Math.max(240, 20 + (showProviderIcon ? baseRowHeight + 8 : 0) + (showQuotaPeriod ? baseCaptionWidth : 0) + (showQuotaValue ? baseValueWidth : 0) + (showResetTime ? baseResetWidth : 0) + (showProgressBar ? 50 : 0) + Math.max(0, quotaColumnCount - 1) * 6))
    readonly property real minimumWidgetHeight: Math.ceil(20 + (showTitle ? baseTitle.implicitHeight + 4 : 0) + Math.max(baseRowHeight, providerCount * baseRowHeight + Math.max(0, providerCount - 1) * 4) + 4 + Math.max(24, baseLineHeight + 8))
    // Only unscaled metrics feed minimums, so resizing cannot cause a binding loop.
    readonly property real uiScale: Math.max(1, Math.min(1.5, width / minimumWidgetWidth, height / minimumWidgetHeight))
    readonly property var oldestData: Lib.oldestTimestamp(report)
    property double ageNowMs: Date.now()
    property double observedQuotaClockMs: 0
    signal refreshRequested
    implicitWidth: Math.max(300, minimumWidgetWidth)
    implicitHeight: minimumWidgetHeight
    Layout.minimumWidth: minimumWidgetWidth
    Layout.minimumHeight: minimumWidgetHeight
    Layout.preferredWidth: implicitWidth
    Layout.preferredHeight: implicitHeight
    padding: 10 * uiScale

    FontMetrics { id: labelMetrics; font: Lib.scaledFont(full.labelFont, 1) }
    PC.Label { id: baseLabel; visible: false; font: Lib.scaledFont(full.labelFont, 1); text: "100.0%" }
    PC.Label { id: baseTitle; visible: false; font: Lib.scaledFont(Kirigami.Theme.defaultFont, 1, Font.DemiBold); text: "AI Quotes" }

    function textWidth(text) {
        // Track font changes: advanceWidth() itself has no change signal.
        const metricsFont = labelMetrics.font;
        return labelMetrics.advanceWidth(text);
    }

    function measuredValueWidth() {
        let width = textWidth("100.0%");
        (full.report ? full.report.providers : []).forEach(function (provider) {
            Lib.displayWindows(provider).forEach(function (window) {
                // Measure the reported value even after expiry to keep its space.
                width = Math.max(width, textWidth(Lib.quotaValue(window)));
            });
        });
        return Math.ceil(width);
    }

    function updateAge() {
        ageTimer.stop();
        full.ageNowMs = Date.now();
        if (full.visible && full.oldestData !== null) {
            ageTimer.interval = Lib.nextAgeInterval(full.oldestData, full.ageNowMs);
            ageTimer.start();
        }
    }
    onReportChanged: Qt.callLater(full.updateAge)
    onOldestDataChanged: updateAge()
    onVisibleChanged: updateAge()
    // A suspended process or adjusted system clock must not keep a stale label
    // until its old timer deadline. Normal five-second quota ticks do no work.
    onNowMsChanged: {
        const delta = full.nowMs - full.observedQuotaClockMs;
        full.observedQuotaClockMs = full.nowMs;
        if (full.visible && (delta < 0 || delta > 15000)) full.updateAge();
    }
    Component.onCompleted: {
        full.observedQuotaClockMs = full.nowMs;
        full.updateAge();
    }
    Timer {
        id: ageTimer
        objectName: "ageTimer"
        repeat: false
        onTriggered: full.updateAge()
    }

    background: Rectangle {
        objectName: "translucentSurface"
        radius: 12
        color: Qt.rgba(full.surfaceColor.r, full.surfaceColor.g, full.surfaceColor.b, Math.max(0, Math.min(100, full.backgroundOpacity)) / 100)
    }

    contentItem: ColumnLayout {
        spacing: 4 * full.uiScale
        PC.Label {
            id: heading
            objectName: "widgetTitle"
            visible: full.showTitle
            Layout.fillWidth: true
            text: full.effectiveTitle
            textFormat: Text.PlainText
            elide: Text.ElideRight
            horizontalAlignment: full.titleAlignment === 1 ? Text.AlignHCenter : full.titleAlignment === 2 ? Text.AlignRight : Text.AlignLeft
            color: full.inkColor
            font: Lib.scaledFont(Kirigami.Theme.defaultFont, full.uiScale, Font.DemiBold)
            Accessible.name: full.effectiveTitle
        }
        ColumnLayout {
            objectName: "providerList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 4 * full.uiScale
            Repeater {
                model: full.report ? full.report.providers : []
                delegate: PlasmaCore.ToolTipArea {
                    id: provider
                    required property var modelData
                    objectName: "provider_" + modelData.id
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: full.baseRowHeight * full.uiScale
                    readonly property bool current: Lib.validProvider(modelData, full.nowMs, full.maxAge)
                    readonly property var headline: Lib.headline(modelData, full.nowMs, full.maxAge)
                    readonly property var displayedWindows: Lib.displayWindows(modelData)
                    readonly property bool stale: Lib.isStale(modelData, full.nowMs, full.maxAge)
                    readonly property string tooltipText: Lib.providerTooltip(modelData, full.nowMs, full.maxAge)
                    mainText: modelData.label
                    subText: tooltipText
                    textFormat: Text.PlainText
                    // The stock native tooltip limits its subtext line count.
                    // Keep its window, but provide an untruncated content item.
                    mainItem: Item {
                        implicitWidth: {
                            let width = 0;
                            provider.tooltipText.split("\n").forEach(function (line) {
                                width = Math.max(width, full.textWidth(line));
                            });
                            return Math.max(1, Math.min(360, Math.ceil(width) + 12, Screen.desktopAvailableWidth - 32));
                        }
                        implicitHeight: tooltipLabel.implicitHeight + 12
                        Kirigami.Theme.colorSet: Kirigami.Theme.Window
                        Kirigami.Theme.inherit: false
                        PC.Label {
                            id: tooltipLabel
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 6
                            text: provider.tooltipText
                            font: full.labelFont
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                        }
                    }
                    onContainsMouseChanged: {
                        if (activeFocus) Qt.callLater(showToolTip);
                    }
                    onActiveFocusChanged: {
                        if (activeFocus) showToolTip();
                        else hideToolTip();
                    }
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Grouping
                    Accessible.name: modelData.label
                    Accessible.description: tooltipText
                    HoverHandler { id: providerHover }
                    Rectangle {
                        anchors.fill: parent
                        radius: 6
                        color: full.inkColor
                        opacity: providerHover.hovered || provider.activeFocus ? 0.04 : 0
                    }
                    RowLayout {
                        anchors.fill: parent
                        spacing: 8 * full.uiScale
                        Item {
                            visible: full.showProviderIcon
                            Layout.preferredWidth: full.baseRowHeight * full.uiScale
                            Layout.preferredHeight: full.baseRowHeight * full.uiScale
                            Layout.alignment: Qt.AlignVCenter
                            Image {
                                objectName: "icon_" + provider.modelData.id
                                anchors.fill: parent
                                source: Qt.resolvedUrl("../icons/" + provider.modelData.id + ".svg")
                                sourceSize.width: Math.ceil(width)
                                sourceSize.height: Math.ceil(height)
                                fillMode: Image.PreserveAspectFit
                                opacity: provider.headline && !provider.stale ? 1 : 0.45
                            }
                            Kirigami.Icon {
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                width: 12 * full.uiScale
                                height: width
                                source: "dialog-warning"
                                visible: provider.stale
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 4 * full.uiScale
                            Repeater {
                                model: provider.current ? provider.displayedWindows : []
                                delegate: RowLayout {
                                    id: window
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: 6 * full.uiScale
                                    readonly property bool live: Lib.liveWindow(provider.modelData, modelData, full.nowMs, full.maxAge)
                                    readonly property bool hasPercent: live && typeof modelData.remaining_percent === "number" && isFinite(modelData.remaining_percent)
                                    QuotaBar {
                                        id: quotaBar
                                        objectName: "bar_" + provider.modelData.id + "_" + window.modelData.key
                                        visible: full.showQuotaPeriod || full.showProgressBar || full.showQuotaValue
                                        Layout.fillWidth: true
                                        showCaption: full.showQuotaPeriod
                                        showTrack: full.showProgressBar
                                        showValue: full.showQuotaValue
                                        scaleFactor: full.uiScale
                                        labelFont: full.labelFont
                                        captionWidth: full.baseCaptionWidth * full.uiScale
                                        valueWidth: full.baseValueWidth * full.uiScale
                                        value: window.hasPercent ? Math.max(0, Math.min(100, window.modelData.remaining_percent)) : 0
                                        hasPercent: window.hasPercent
                                        opacity: provider.stale ? 0.6 : 1
                                        caption: Lib.shortWindowLabel(window.modelData)
                                        inkColor: full.inkColor
                                        accentColor: Lib.colorFor(provider.modelData.id)
                                        valueObjectName: "quota_" + provider.modelData.id + "_" + window.modelData.key
                                        valueText: Lib.valueFor(provider.modelData, window.modelData, full.nowMs, full.maxAge)
                                        Accessible.name: provider.modelData.label + ", " + window.modelData.label + ", " + i18n("available") + ": " + valueText
                                    }
                                    Item {
                                        visible: !quotaBar.visible
                                        Layout.fillWidth: true
                                    }
                                    PC.Label {
                                        objectName: "reset_" + provider.modelData.id + "_" + window.modelData.key
                                        visible: full.showResetTime
                                        text: window.live ? Lib.shortCountdown(window.modelData.resets_at, full.nowMs) : "—"
                                        Layout.preferredWidth: full.baseResetWidth * full.uiScale
                                        Layout.alignment: Qt.AlignVCenter
                                        horizontalAlignment: Text.AlignHCenter
                                        color: full.inkColor
                                        opacity: provider.stale ? 0.6 : 0.75
                                        font: full.scaledLabelFont
                                    }
                                }
                            }
                            PC.Label {
                                visible: !provider.current || provider.displayedWindows.length === 0
                                text: provider.modelData.label + "\n" + (provider.modelData.message || i18n("Waiting for a new query"))
                                textFormat: Text.PlainText
                                color: full.inkColor
                                Layout.fillWidth: true
                                maximumLineCount: 2
                                wrapMode: Text.WordWrap
                                elide: Text.ElideRight
                                opacity: 0.65
                                font: full.scaledLabelFont
                            }
                        }
                    }
                }
            }
            PC.Label {
                visible: !full.report || full.providerCount === 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: full.loading ? i18n("Querying your accounts…") : i18n("Select providers in the settings.")
                color: full.inkColor
                font: full.scaledLabelFont
                wrapMode: Text.WordWrap
            }
        }
        RowLayout {
            objectName: "footer"
            Layout.fillWidth: true
            spacing: 6 * full.uiScale
            PC.Label {
                id: errorLabel
                objectName: "lastError"
                Layout.fillWidth: true
                text: full.lastError
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: full.negativeColor
                font: full.scaledLabelFont
                Accessible.description: text
                HoverHandler { id: errorHover }
                PC.ToolTip {
                    parent: errorLabel
                    text: full.lastError
                    textFormat: Text.PlainText
                    visible: errorHover.hovered && text.length > 0
                }
            }
            PC.Label {
                id: ageLabel
                objectName: "lastUpdated"
                text: Lib.shortAge(full.oldestData, full.ageNowMs)
                color: full.inkColor
                opacity: 0.65
                font: full.scaledLabelFont
                Accessible.name: i18n("Oldest data") + ": " + text
                HoverHandler { id: ageHover }
                PC.ToolTip {
                    parent: ageLabel
                    text: Lib.footerTooltip(full.report, full.nowMs, full.maxAge)
                    textFormat: Text.PlainText
                    visible: ageHover.hovered
                }
            }
            PC.ToolButton {
                objectName: "refreshButton"
                id: refreshButton
                Layout.preferredWidth: 24 * full.uiScale
                Layout.preferredHeight: 24 * full.uiScale
                icon.name: "view-refresh"
                display: PC.AbstractButton.IconOnly
                text: i18n("Refresh quotas")
                enabled: !full.loading
                onClicked: full.refreshRequested()
                PC.ToolTip.text: text + " · " + Lib.attemptLabel(full.report ? full.report.generated_at : null, full.nowMs)
                PC.ToolTip.visible: hovered || activeFocus
                contentItem: Image {
                    source: "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="' + full.inkColor + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 6A4.5 4.5 0 1 0 12 10M8.5 6H12V2.5"/></svg>')
                    sourceSize.width: Math.ceil(14 * full.uiScale)
                    sourceSize.height: Math.ceil(14 * full.uiScale)
                    fillMode: Image.PreserveAspectFit
                    opacity: refreshButton.enabled ? 0.8 : 0.3
                }
                padding: 5 * full.uiScale
                background: Rectangle {
                    radius: 6
                    color: full.inkColor
                    opacity: refreshButton.down ? 0.12 : refreshButton.hovered || refreshButton.activeFocus ? 0.06 : 0
                }
            }
        }
    }
}
