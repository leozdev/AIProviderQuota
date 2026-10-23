pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PC
import org.kde.kirigami as Kirigami
import "lib.js" as Lib

MouseArea {
    id: compact
    property var report: null
    property double nowMs: Date.now()
    property int maxAge: 600
    readonly property string quotaDescription: compact.report ? compact.report.providers.map(function (p) {
        return Lib.providerSummary(p, compact.nowMs, compact.maxAge);
    }).join("\n") : ""
    implicitWidth: chips.implicitWidth + 12
    implicitHeight: Kirigami.Units.iconSizes.smallMedium
    activeFocusOnTab: true
    onPressed: compact.forceActiveFocus()
    Accessible.role: Accessible.Button
    Accessible.name: i18n("Open AI Quotes") + (quotaDescription ? "\n" + quotaDescription : "")
    Keys.onReturnPressed: compact.clicked(null)
    Keys.onEnterPressed: compact.clicked(null)
    Keys.onSpacePressed: compact.clicked(null)
    RowLayout {
        id: chips
        anchors.centerIn: parent
        spacing: 12
        Repeater {
            model: compact.report ? compact.report.providers : []
            delegate: RowLayout {
                id: chip
                required property var modelData
                spacing: 4
                readonly property var headline: Lib.headline(modelData, compact.nowMs, compact.maxAge)
                Image {
                    objectName: "panel_icon_" + chip.modelData.id
                    source: Qt.resolvedUrl("../icons/" + chip.modelData.id + ".svg")
                    sourceSize.width: 16
                    sourceSize.height: 16
                    Layout.preferredWidth: 16
                    Layout.preferredHeight: 16
                    fillMode: Image.PreserveAspectFit
                    opacity: chip.headline ? 1 : 0.35
                }
                PC.Label {
                    text: chip.headline ? Lib.valueFor(chip.modelData, chip.headline, compact.nowMs, compact.maxAge) : "—"
                    opacity: chip.modelData.state === "stale" ? 0.6 : 1
                }
            }
        }
        PC.Label {
            visible: !compact.report
            text: i18n("AI Quotes")
        }
    }
}
