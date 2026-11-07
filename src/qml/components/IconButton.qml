import QtQuick
import QtQuick.Controls.Material
import ".."

ToolButton {
    id: root
    required property string symbol
    required property string description
    implicitWidth: 42
    implicitHeight: 42
    Accessible.name: description
    ToolTip.text: description
    ToolTip.visible: hovered
    contentItem: Item {
        Icon {
            anchors.centerIn: parent
            width: 20
            height: 20
            name: root.symbol
            color: root.enabled ? Theme.muted : Theme.outline
        }
    }
}
