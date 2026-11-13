import QtQuick
import QtQuick.Controls.Material
import Entropy

Drawer {
    id: root
    required property AppController controller
    parent: Overlay.overlay
    signal chooseOutput
    edge: Qt.RightEdge
    width: Math.min(380, parent.width - 40)
    height: parent.height
    contentItem: SettingsPanel {
        controller: root.controller
        onChooseOutput: root.chooseOutput()
    }
}
