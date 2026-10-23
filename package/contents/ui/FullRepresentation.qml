pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PC
import org.kde.kirigami as Kirigami
import "lib.js" as Lib

// Page/ScrollView absorb every mouse button; let Plasma receive right presses.
PC.Control {
    id: full
    property var report: null
    property bool loading: false
    property string lastError: ""
    property double nowMs: Date.now()
    property int maxAge: 600
    property string expandedId: ""
    // 0 follows Plasma; 1 and 2 override only this widget's appearance.
    property int themeMode: 0
    property int backgroundOpacity: 82
    readonly property color surfaceColor: themeMode === 1 ? "#f8fafc" : themeMode === 2 ? "#171c25" : Kirigami.Theme.backgroundColor
    readonly property color inkColor: themeMode === 1 ? "#17212d" : themeMode === 2 ? "#f1f5f9" : Kirigami.Theme.textColor
    readonly property color warningColor: themeMode === 1 ? "#9a6700" : themeMode === 2 ? "#f5c46b" : Kirigami.Theme.neutralTextColor
    readonly property color negativeColor: themeMode === 1 ? "#c02832" : themeMode === 2 ? "#ff7b86" : Kirigami.Theme.negativeTextColor
    signal refreshRequested
    implicitWidth: 300
    implicitHeight: 180
    Layout.minimumWidth: 280
    Layout.minimumHeight: 180
    Layout.preferredWidth: 300
    Layout.preferredHeight: 180
    padding: 10

    background: Rectangle {
        objectName: "translucentSurface"
        radius: 12
        color: Qt.rgba(full.surfaceColor.r, full.surfaceColor.g, full.surfaceColor.b, Math.max(0, Math.min(100, full.backgroundOpacity)) / 100)
        border.width: 1
        border.color: Qt.rgba(full.inkColor.r, full.inkColor.g, full.inkColor.b, 0.07)
    }

    function quotaColor(value, providerId) {
        if (typeof value !== "number")
            return full.inkColor;
        if (value <= 10)
            return full.negativeColor;
        if (value <= 25)
            return full.warningColor;
        return Lib.colorFor(providerId);
    }

    contentItem: ColumnLayout {
        spacing: 4
        RowLayout {
            Layout.fillWidth: true
            PC.Label {
                text: i18n("Cotas de IA")
                color: full.inkColor
                font.weight: Font.DemiBold
                font.pointSize: Kirigami.Theme.defaultFont.pointSize
                Layout.fillWidth: true
            }
            PC.ToolButton {
                objectName: "refreshButton"
                id: refreshButton
                Layout.preferredWidth: 24
                Layout.preferredHeight: 24
                Layout.maximumHeight: 24
                icon.name: "view-refresh"
                display: PC.AbstractButton.IconOnly
                text: i18n("Atualizar quotas")
                enabled: !full.loading
                onClicked: full.refreshRequested()
                PC.ToolTip.text: text + " · " + Lib.attemptLabel(full.report ? full.report.generated_at : null, full.nowMs)
                PC.ToolTip.visible: hovered
                contentItem: Image {
                    // Explicit stroke also follows forced themes when the icon
                    // loader keeps the platform's original symbolic palette.
                    source: "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="' + full.inkColor + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 6A4.5 4.5 0 1 0 12 10M8.5 6H12V2.5"/></svg>')
                    sourceSize.width: 14
                    sourceSize.height: 14
                    fillMode: Image.PreserveAspectFit
                    opacity: refreshButton.enabled ? 0.8 : 0.3
                }
                padding: 5
                background: Rectangle {
                    radius: 6
                    color: full.inkColor
                    opacity: refreshButton.down ? 0.12 : refreshButton.hovered || refreshButton.activeFocus ? 0.06 : 0
                }
            }
        }

        Flickable {
            id: scroll
            objectName: "providerScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: providerList.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            PC.ScrollBar.vertical: PC.ScrollBar {
                id: verticalScrollBar
                objectName: "providerScrollBar"
            }
            Kirigami.WheelHandler {
                target: scroll
            }
            ColumnLayout {
                id: providerList
                width: scroll.width - (verticalScrollBar.visible ? verticalScrollBar.width : 0)
                spacing: 4
                Repeater {
                    model: full.report ? full.report.providers : []
                    delegate: ColumnLayout {
                        id: provider
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 2
                        readonly property bool current: Lib.validProvider(modelData, full.nowMs, full.maxAge)
                        readonly property var headline: Lib.headline(modelData, full.nowMs, full.maxAge)
                        readonly property var displayedWindows: Lib.displayWindows(modelData)
                        readonly property bool stale: Lib.isStale(modelData, full.nowMs, full.maxAge)

                        PC.ItemDelegate {
                            id: providerButton
                            objectName: "provider_" + provider.modelData.id
                            Layout.fillWidth: true
                            implicitHeight: Math.max(40, contentItem.implicitHeight + topPadding + bottomPadding)
                            topPadding: 2
                            bottomPadding: 2
                            leftPadding: 2
                            rightPadding: 2
                            onClicked: full.expandedId = full.expandedId === provider.modelData.id ? "" : provider.modelData.id
                            Accessible.name: provider.modelData.label + ", " + (provider.current ? i18n("quota disponível") : i18n("indisponível"))
                            background: Rectangle {
                                radius: 6
                                color: full.inkColor
                                opacity: providerButton.down ? 0.08 : providerButton.hovered || providerButton.activeFocus ? 0.04 : 0
                            }
                            contentItem: RowLayout {
                                spacing: 8
                                Item {
                                    Layout.preferredWidth: 36
                                    Layout.fillHeight: true
                                    implicitHeight: 36
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
                                        width: 12
                                        height: 12
                                        source: "dialog-warning"
                                        visible: provider.stale
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.alignment: Qt.AlignVCenter
                                    spacing: 4
                                    Repeater {
                                        model: provider.current ? provider.displayedWindows : []
                                        delegate: RowLayout {
                                            id: window
                                            required property var modelData
                                            Layout.fillWidth: true
                                            spacing: 6
                                            readonly property bool live: Lib.liveWindow(provider.modelData, modelData, full.nowMs, full.maxAge)
                                            readonly property bool hasPercent: live && typeof modelData.remaining_percent === "number" && isFinite(modelData.remaining_percent)
                                            QuotaBar {
                                                id: bar
                                                objectName: "bar_" + provider.modelData.id + "_" + window.modelData.key
                                                Layout.fillWidth: true
                                                value: window.hasPercent ? Math.max(0, Math.min(100, window.modelData.remaining_percent)) : 0
                                                hasPercent: window.hasPercent
                                                opacity: provider.stale ? 0.6 : 1
                                                caption: Lib.shortWindowLabel(window.modelData)
                                                inkColor: full.inkColor
                                                accentColor: full.quotaColor(window.hasPercent ? window.modelData.remaining_percent : null, provider.modelData.id)
                                                valueObjectName: "quota_" + provider.modelData.id + "_" + window.modelData.key
                                                valueText: Lib.valueFor(provider.modelData, window.modelData, full.nowMs, full.maxAge)
                                                Accessible.name: provider.modelData.label + ", " + window.modelData.label + ", " + i18n("disponível") + ": " + valueText
                                            }
                                            PC.Label {
                                                objectName: "reset_" + provider.modelData.id + "_" + window.modelData.key
                                                text: window.live ? Lib.shortCountdown(window.modelData.resets_at, full.nowMs) : "—"
                                                Layout.preferredWidth: 26
                                                Layout.alignment: Qt.AlignVCenter
                                                horizontalAlignment: Text.AlignHCenter
                                                verticalAlignment: Text.AlignVCenter
                                                color: full.inkColor
                                                opacity: provider.stale ? 0.6 : 0.75
                                                font: Kirigami.Theme.smallFont
                                            }
                                        }
                                    }
                                    PC.Label {
                                        visible: !provider.current || provider.displayedWindows.length === 0
                                        text: provider.modelData.label + "\n" + (provider.modelData.message || i18n("Aguardando nova consulta"))
                                        color: full.inkColor
                                        Layout.fillWidth: true
                                        maximumLineCount: 2
                                        wrapMode: Text.WordWrap
                                        elide: Text.ElideRight
                                        opacity: 0.65
                                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                                    }
                                }
                            }
                            PC.ToolTip.visible: hovered
                            PC.ToolTip.text: Lib.providerTooltip(provider.modelData, provider.displayedWindows, full.nowMs, full.maxAge)
                        }

                        ColumnLayout {
                            visible: full.expandedId === provider.modelData.id
                            Layout.fillWidth: true
                            Layout.leftMargin: 46
                            Layout.rightMargin: 8
                            spacing: 5
                            PC.Label {
                                text: provider.modelData.label
                                color: full.inkColor
                                font.bold: true
                            }
                            Repeater {
                                model: provider.modelData.windows
                                delegate: ColumnLayout {
                                    id: detail
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: 1
                                    PC.Label {
                                        text: detail.modelData.label + ": " + Lib.valueFor(provider.modelData, detail.modelData, full.nowMs, full.maxAge)
                                        color: full.inkColor
                                        Layout.fillWidth: true
                                        wrapMode: Text.WordWrap
                                    }
                                    PC.Label {
                                        text: Lib.countdown(detail.modelData.resets_at, full.nowMs)
                                            + (detail.modelData.resets_at ? " · " + Qt.formatDateTime(new Date(detail.modelData.resets_at * 1000), "dd/MM HH:mm") : "")
                                        Layout.fillWidth: true
                                        color: full.inkColor
                                        opacity: 0.65
                                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                                    }
                                }
                            }
                            PC.Label {
                                text: provider.modelData.message
                                visible: text.length > 0
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                color: provider.modelData.state === "auth" ? full.negativeColor : full.inkColor
                            }
                            PC.Label {
                                text: provider.modelData.source + (provider.modelData.source ? "\n" : "") + Lib.ageLabel(provider.modelData.fetched_at, full.nowMs)
                                color: full.inkColor
                                Layout.fillWidth: true
                                wrapMode: Text.WordWrap
                                opacity: 0.55
                                font.pointSize: Kirigami.Theme.smallFont.pointSize
                            }
                        }
                    }
                }
                PC.Label {
                    visible: !full.report || full.report.providers.length === 0
                    text: full.loading ? i18n("Consultando suas contas…") : i18n("Selecione os provedores nas configurações.")
                    color: full.inkColor
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    opacity: 0.65
                }
            }
        }
        PC.Label {
            visible: full.lastError.length > 0
            text: full.lastError
            color: full.inkColor
            Layout.fillWidth: true
            elide: Text.ElideRight
            opacity: 0.6
            font.pointSize: Kirigami.Theme.smallFont.pointSize
        }
    }
}
