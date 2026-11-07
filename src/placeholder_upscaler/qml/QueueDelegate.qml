import QtQuick
import QtQuick.Controls.Material
import QtQuick.Layouts

ItemDelegate {
    id: root
    required property int index
    required property var model
    required property bool selected
    signal chosen(int row)
    readonly property var labels: ({
                                       "Ready": qsTr("Ready"),
                                       "Queued": qsTr("Queued"),
                                       "Processing": qsTr("Processing"),
                                       "Done": qsTr("Done"),
                                       "Failed": qsTr("Failed"),
                                       "Cancelled": qsTr("Cancelled"),
                                       "Not completed": qsTr("Not completed")
                                   })
    width: 164
    height: 126
    padding: 10
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    Accessible.name: qsTr("%1 · %2").arg(model.fileName).arg(labels[model.state] || model.state)
    ToolTip.text: model.errorText || model.fileName
    ToolTip.visible: hovered
    onClicked: chosen(index)
    background: Rectangle {
        radius: 12
        color: root.selected ? Theme.accentSurface : root.hovered ? Theme.raised : Theme.surface
        border.color: root.selected ? Theme.accent : Theme.outline
        border.width: root.selected ? 2 : 1
    }
    contentItem: ColumnLayout {
        spacing: 4
        Image {
            id: thumbnail
            Layout.fillWidth: true
            Layout.fillHeight: true
            source: root.model.previewUrl
            sourceSize: Qt.size(144, 64)
            fillMode: Image.PreserveAspectFit
            autoTransform: true
            asynchronous: true
            Accessible.ignored: true
        }
        Label {
            Layout.fillWidth: true
            text: root.model.fileName
            elide: Text.ElideMiddle
            color: Theme.text
            font.pointSize: Theme.caption
        }
        Label {
            Layout.fillWidth: true
            text: thumbnail.status === Image.Error ? qsTr("No preview") :
                                                     root.labels[root.model.state]
                                                     || root.model.state
            color: root.model.state === "Failed" ? Theme.error : root.model.state === "Done"
                                                   ? Theme.success : Theme.muted
            font.pointSize: Theme.caption
        }
    }
}
