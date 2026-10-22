pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PC
import org.kde.kirigami as Kirigami

PC.ProgressBar {
    id: meter
    property string caption: ""
    property string valueText: "—"
    property string valueObjectName: ""
    property bool hasPercent: true
    property color inkColor: Kirigami.Theme.textColor
    property color accentColor: Kirigami.Theme.highlightColor
    from: 0
    to: 100
    padding: 0
    implicitHeight: Math.max(16, valueLabel.implicitHeight)
    background: null
    Accessible.role: hasPercent ? Accessible.ProgressBar : Accessible.StaticText
    contentItem: RowLayout {
        spacing: 6
        PC.Label {
            objectName: meter.objectName + "_caption"
            text: meter.caption
            color: meter.inkColor
            opacity: 0.8
            Layout.preferredWidth: 26
            elide: Text.ElideRight
            font: Kirigami.Theme.smallFont
        }
        Item {
            objectName: meter.objectName + "_track"
            Layout.fillWidth: true
            Layout.preferredHeight: 4
            opacity: meter.hasPercent ? 1 : 0
            Rectangle {
                anchors.fill: parent
                radius: 2
                color: meter.inkColor
                opacity: 0.12
            }
            Rectangle {
                width: meter.visualPosition * parent.width
                height: parent.height
                radius: 2
                color: meter.accentColor
                anchors.right: meter.mirrored ? parent.right : undefined
                anchors.left: meter.mirrored ? undefined : parent.left
            }
        }
        PC.Label {
            id: valueLabel
            objectName: meter.valueObjectName
            text: meter.valueText
            color: meter.inkColor
            horizontalAlignment: Text.AlignRight
            Layout.preferredWidth: Math.max(42, implicitWidth)
            font: Kirigami.Theme.smallFont
        }
    }
}
