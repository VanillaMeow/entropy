import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Entropy
import "components"

Rectangle {
    id: root
    required property AppController controller
    implicitHeight: Math.max(110, content.implicitHeight + 32)
    color: Theme.surface
    Rectangle {
        width: parent.width
        height: 1
        color: Theme.outline
    }
    RowLayout {
        id: content
        anchors.fill: parent
        anchors.leftMargin: 28
        anchors.rightMargin: 28
        anchors.topMargin: 16
        anchors.bottomMargin: 16
        spacing: 18
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 10
            Label {
                Layout.fillWidth: true
                text: root.controller.statusText
                color: root.controller.hasError ? Theme.error : Theme.text
                font.pointSize: Theme.caption
                wrapMode: Text.WordWrap
                maximumLineCount: 3
                elide: Text.ElideRight
                Accessible.role: Accessible.StaticText
            }
            ProgressBar {
                Layout.fillWidth: true
                Layout.maximumWidth: 480
                value: root.controller.progress
                indeterminate: root.controller.indeterminate
                visible: root.controller.busy || value > 0
                Accessible.name: qsTr("Batch progress")
            }
        }
        IconButton {
            symbol: "folder"
            description: qsTr("Open output folder")
            onClicked: root.controller.openOutput()
        }
        ActionButton {
            text: qsTr("Cancel")
            visible: root.controller.busy
            onClicked: root.controller.cancel()
        }
        ActionButton {
            objectName: "upscaleButton"
            primary: true
            symbol: "arrow"
            text: {
                const count = root.controller.queueCount;
                if (root.controller.outputScale < 1)
                    return count > 1 ? qsTr("Downscale %1 images").arg(count) : qsTr(
                                           "Downscale image");
                if (root.controller.outputScale === 1)
                    return count > 1 ? qsTr("Resize %1 images").arg(count) : qsTr("Resize image");
                return count > 1 ? qsTr("Upscale %1 images").arg(count) : qsTr("Upscale image");
            }
            enabled: root.controller.canStart
            onClicked: root.controller.startBatch()
        }
    }
}
