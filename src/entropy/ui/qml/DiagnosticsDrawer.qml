import QtQuick
import QtQuick.Controls.Material
import QtQuick.Layouts
import Upscaler.Backend
import "components"

Drawer {
    id: root
    required property AppController controller
    parent: Overlay.overlay
    edge: Qt.BottomEdge
    width: parent.width
    height: Math.min(380, parent.height * 0.5)
    modal: true
    contentItem: ColumnLayout {
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 16
            Label {
                text: qsTr("Diagnostics")
                color: Theme.text
                font.pointSize: Theme.heading
                Layout.fillWidth: true
            }
            ActionButton {
                objectName: "retrySetupButton"
                text: qsTr("Retry setup")
                symbol: "refresh"
                enabled: !root.controller.busy
                onClicked: root.controller.prepare()
            }
            IconButton {
                symbol: "close"
                description: qsTr("Close diagnostics")
                onClicked: root.close()
            }
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 16
            TextArea {
                text: root.controller.diagnostics || qsTr("No diagnostics yet.")
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.WrapAnywhere
                font.pointSize: Theme.caption
                Accessible.name: qsTr("Runtime diagnostics")
            }
        }
    }
}
