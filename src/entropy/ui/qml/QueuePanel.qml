pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Upscaler.Backend
import "components"

ColumnLayout {
    id: root
    required property AppController controller
    signal addFolder
    spacing: 12
    RowLayout {
        Layout.fillWidth: true
        SectionLabel {
            text: qsTr("YOUR IMAGES · %1").arg(root.controller.queueCount)
        }
        Item {
            Layout.fillWidth: true
        }
        ActionButton {
            text: qsTr("Add folder")
            symbol: "folder"
            compact: true
            enabled: root.controller.canEdit
            onClicked: root.addFolder()
        }
        IconButton {
            symbol: "trash"
            description: qsTr("Remove selected image")
            enabled: root.controller.canEdit && root.controller.selectedIndex >= 0
            onClicked: root.controller.removeSelected()
        }
        ToolButton {
            text: qsTr("Clear")
            enabled: root.controller.canEdit
            onClicked: root.controller.clearQueue()
        }
    }
    ListView {
        id: images
        objectName: "imageQueue"
        Layout.fillWidth: true
        Layout.preferredHeight: 132
        orientation: ListView.Horizontal
        spacing: 10
        clip: true
        reuseItems: true
        activeFocusOnTab: true
        keyNavigationEnabled: false
        Accessible.name: qsTr("Image queue. Use arrow keys to select an image.")
        model: root.controller.queueModel
        currentIndex: root.controller.selectedIndex
        Keys.onRightPressed: root.controller.select(Math.min(root.controller.queueCount - 1,
                                                             root.controller.selectedIndex + 1))
        Keys.onLeftPressed: root.controller.select(Math.max(0, root.controller.selectedIndex - 1))
        Keys.onDeletePressed: root.controller.removeSelected()
        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
        delegate: QueueDelegate {
            selected: index === root.controller.selectedIndex
            onChosen: row => root.controller.select(row)
        }
        ScrollBar.horizontal: ScrollBar {}
    }
}
