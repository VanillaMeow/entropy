pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Upscaler.Backend
import "components"

Rectangle {
    id: root
    required property AppController controller
    signal chooseOutput
    signal addFolder
    color: Theme.surface
    radius: 18
    border.color: Theme.outline
    ScrollView {
        id: scroll
        anchors.fill: parent
        padding: 22
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            width: scroll.availableWidth
            spacing: 12
            ScaleSettings {
                Layout.fillWidth: true
                controller: root.controller
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 1
                color: Theme.outline
            }
            SectionLabel {
                text: qsTr("SAVE TO")
            }
            TextField {
                Layout.fillWidth: true
                text: root.controller.outputDirectory
                enabled: root.controller.canEdit
                Accessible.name: qsTr("Output directory")
                selectByMouse: true
                onEditingFinished: root.controller.outputDirectory = text
            }
            ActionButton {
                Layout.fillWidth: true
                text: qsTr("Choose folder")
                symbol: "folder"
                enabled: root.controller.canEdit
                onClicked: root.chooseOutput()
            }
            Label {
                Layout.fillWidth: true
                text: qsTr("PNG output. Your originals and existing files are always preserved.")
                color: Theme.muted
                font.pointSize: Theme.caption
                wrapMode: Text.WordWrap
            }
            Switch {
                id: advanced
                text: qsTr("Advanced settings")
                enabled: root.controller.canEdit
            }
            Loader {
                Layout.fillWidth: true
                active: advanced.checked
                sourceComponent: AdvancedSettings {
                    controller: root.controller
                }
            }
        }
    }
}
