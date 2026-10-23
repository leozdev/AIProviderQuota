pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PC
import org.kde.kirigami as Kirigami
import "lib.js" as Lib

PC.ProgressBar {
    id: meter
    property real scaleFactor: 1
    property font labelFont: Kirigami.Theme.smallFont
    property real captionWidth: 26
    property real valueWidth: 42
    property string caption: ""
    property string valueText: "—"
    property string valueObjectName: ""
    property bool hasPercent: true
    property bool showCaption: true
    property bool showTrack: true
    property bool showValue: true
    property color inkColor: Kirigami.Theme.textColor
    property color accentColor: Kirigami.Theme.highlightColor
    from: 0
    to: 100
    padding: 0
    implicitHeight: Math.max(16 * scaleFactor, valueLabel.implicitHeight)
    background: null
    Accessible.role: hasPercent && showTrack ? Accessible.ProgressBar : Accessible.StaticText
    contentItem: RowLayout {
        spacing: 6 * meter.scaleFactor
        PC.Label {
            objectName: meter.objectName + "_caption"
            visible: meter.showCaption
            text: meter.caption
            color: meter.inkColor
            opacity: 0.8
            Layout.preferredWidth: meter.captionWidth
            Layout.fillWidth: !meter.showTrack && !meter.showValue
            elide: Text.ElideRight
            font: Lib.scaledFont(meter.labelFont, meter.scaleFactor)
        }
        Item {
            objectName: meter.objectName + "_track"
            visible: meter.showTrack
            Layout.fillWidth: true
            Layout.preferredHeight: 4 * meter.scaleFactor
            opacity: meter.hasPercent ? 1 : 0
            Rectangle {
                anchors.fill: parent
                radius: 2 * meter.scaleFactor
                color: meter.inkColor
                opacity: 0.12
            }
            Rectangle {
                width: meter.visualPosition * parent.width
                height: parent.height
                radius: 2 * meter.scaleFactor
                color: meter.accentColor
                anchors.right: meter.mirrored ? parent.right : undefined
                anchors.left: meter.mirrored ? undefined : parent.left
            }
        }
        PC.Label {
            id: valueLabel
            objectName: meter.valueObjectName
            visible: meter.showValue
            text: meter.valueText
            color: meter.inkColor
            horizontalAlignment: Text.AlignRight
            Layout.preferredWidth: Math.max(meter.valueWidth, implicitWidth)
            Layout.fillWidth: !meter.showTrack
            font: Lib.scaledFont(meter.labelFont, meter.scaleFactor)
        }
    }
}
