import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import ".."

Button {
    id: root
    property string symbol: ""
    property bool primary: false
    property bool compact: false
    implicitHeight: compact ? 38 : 46
    implicitWidth: contentItem.implicitWidth + leftPadding + rightPadding
    leftPadding: 18
    rightPadding: 18
    font.pointSize: Theme.body
    font.weight: Font.Medium
    hoverEnabled: true
    contentItem: RowLayout {
        spacing: 9
        Icon {
            visible: root.symbol !== ""
            name: root.symbol
            color: !root.enabled ? Theme.muted : root.primary ? Theme.onAccent : Theme.text
        }
        Label {
            text: root.text
            font: root.font
            color: !root.enabled ? Theme.muted : root.primary ? Theme.onAccent : Theme.text
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }
    }
    background: Rectangle {
        radius: 11
        color: root.enabled && root.primary ? (root.down ? Qt.darker(Theme.accent, 1.12) :
                                                           Theme.accent) : (root.hovered
                                                                            ? Theme.raised :
                                                                              Theme.surface)
        border.color: root.visualFocus ? Theme.accent : root.primary && root.enabled ? Theme.accent :
                                                                                       Theme.outline
        border.width: root.visualFocus ? 2 : 1
    }
}
