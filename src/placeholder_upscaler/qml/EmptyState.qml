import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

ColumnLayout {
    id: root
    signal addImages
    spacing: 18
    Rectangle {
        Layout.alignment: Qt.AlignHCenter
        implicitWidth: 76
        implicitHeight: 76
        radius: 23
        color: Theme.accentSurface
        Icon {
            anchors.centerIn: parent
            width: 32
            height: 32
            name: "upload"
            color: Theme.accent
        }
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("More detail starts here.")
        color: Theme.text
        font.pointSize: Theme.title
        font.weight: Font.Medium
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
    }
    Label {
        Layout.fillWidth: true
        text: qsTr("Drop your images here, or choose them from your device.")
        color: Theme.muted
        font.pointSize: Theme.body
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
    }
    ActionButton {
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: 8
        text: qsTr("Choose images")
        symbol: "add"
        primary: true
        onClicked: root.addImages()
    }
    Label {
        Layout.fillWidth: true
        Layout.topMargin: 4
        text: qsTr("PNG, JPEG, WebP, TIFF and BMP")
        color: Theme.muted
        font.pointSize: Theme.caption
        horizontalAlignment: Text.AlignHCenter
    }
}
