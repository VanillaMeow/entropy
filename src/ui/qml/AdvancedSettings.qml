import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Upscaler.Backend

ColumnLayout {
    id: root
    required property AppController controller
    spacing: 12
    Label {
        text: qsTr("Tile size")
        color: Theme.text
    }
    ComboBox {
        Layout.fillWidth: true
        readonly property var sizes: [32, 64, 128, 256, 512]
        model: sizes
        currentIndex: sizes.indexOf(root.controller.tileSize)
        enabled: root.controller.canEdit
        Accessible.name: qsTr("Tile size in pixels")
        onActivated: root.controller.tileSize = sizes[currentIndex]
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Smaller tiles use less GPU memory.")
        color: Theme.muted
        font.pointSize: Theme.caption
        wrapMode: Text.WordWrap
    }
    Label {
        text: qsTr("Tile padding")
        color: Theme.text
    }
    SpinBox {
        Layout.fillWidth: true
        from: 0
        to: 128
        value: root.controller.padding
        enabled: root.controller.canEdit
        Accessible.name: qsTr("Tile padding in pixels")
        onValueModified: root.controller.padding = value
    }
}
