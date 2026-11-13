pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Entropy

Item {
    id: root
    required property AppController controller
    required property bool wide
    signal addImages
    signal addFolder
    signal chooseOutput
    RowLayout {
        anchors.fill: parent
        spacing: 22
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 28
            Layout.bottomMargin: 22
            Layout.rightMargin: root.wide ? 0 : 28
            spacing: 18
            ComparisonView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                controller: root.controller
                onAddImages: root.addImages()
            }
            QueuePanel {
                Layout.fillWidth: true
                visible: root.controller.queueCount > 0
                controller: root.controller
                onAddFolder: root.addFolder()
            }
        }
        Loader {
            Layout.preferredWidth: 310
            Layout.fillHeight: true
            Layout.rightMargin: 28
            Layout.bottomMargin: 22
            active: root.wide
            visible: active
            sourceComponent: SettingsPanel {
                controller: root.controller
                onChooseOutput: root.chooseOutput()
                onAddFolder: root.addFolder()
            }
        }
    }
    DropArea {
        anchors.fill: parent
        enabled: root.controller.canEdit
        onEntered: drag => {
            drag.accepted = drag.hasUrls;
        }
        onDropped: drop => {
            if (drop.hasUrls) {
                root.controller.addUrls(drop.urls);
                drop.acceptProposedAction();
            }
        }
        Rectangle {
            anchors.fill: parent
            visible: parent.containsDrag
            color: "transparent"
            radius: 18
            border.width: 2
            border.color: Theme.accent
        }
    }
}
