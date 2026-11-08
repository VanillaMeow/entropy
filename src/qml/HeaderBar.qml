import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Upscaler.Backend
import "components"

Rectangle {
    id: root
    required property AppController controller
    property bool compact: false
    signal addImages
    signal addFolder
    signal settingsRequested
    signal diagnosticsRequested
    implicitHeight: 98
    color: Theme.background
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 28
        anchors.rightMargin: 28
        spacing: 14
        Rectangle {
            implicitWidth: 44
            implicitHeight: 44
            color: Theme.accentSurface
            radius: 13
            Icon {
                anchors.centerIn: parent
                name: "expand"
                color: Theme.accent
            }
        }
        ColumnLayout {
            spacing: 1
            RowLayout {
                spacing: 10
                Label {
                    text: qsTr("Entropy")
                    color: Theme.text
                    font.pointSize: Theme.heading
                    font.weight: Font.DemiBold
                }
                Label {
                    objectName: "appVersionLabel"
                    text: qsTr("v%1").arg(Qt.application.version)
                    color: Theme.muted
                    font.pointSize: Theme.caption
                }
            }
            Label {
                text: qsTr("A closer look, a clearer image.")
                color: Theme.muted
                font.pointSize: Theme.caption
            }
        }
        Item {
            Layout.fillWidth: true
        }
        ActionButton {
            text: qsTr("Add images")
            symbol: "add"
            enabled: root.controller.canEdit
            onClicked: root.addImages()
        }
        IconButton {
            symbol: "folder"
            description: qsTr("Add images from a folder")
            enabled: root.controller.canEdit
            onClicked: root.addFolder()
        }
        IconButton {
            symbol: "info"
            description: qsTr("Open diagnostics")
            onClicked: root.diagnosticsRequested()
        }
        IconButton {
            symbol: root.controller.darkTheme ? "sun" : "moon"
            description: root.controller.darkTheme ? qsTr("Use light theme") : qsTr(
                                                         "Use dark theme")
            onClicked: root.controller.darkTheme = !root.controller.darkTheme
        }
        IconButton {
            visible: root.compact
            symbol: "settings"
            description: qsTr("Open settings")
            onClicked: root.settingsRequested()
        }
    }
}
