import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Upscaler.Backend
import "components"

Rectangle {
    id: root
    required property AppController controller
    signal addImages
    readonly property bool hasImage: controller.selectedIndex >= 0
    readonly property bool hasResult: controller.hasResult
    color: Theme.surface
    radius: 18
    border.color: Theme.outline
    implicitHeight: 420
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 16
        RowLayout {
            Layout.fillWidth: true
            SectionLabel {
                text: qsTr("WORKSPACE")
            }
            Item {
                Layout.fillWidth: true
            }
            Label {
                visible: root.hasImage
                text: root.controller.selectedName
                color: Theme.muted
                font.pointSize: Theme.caption
                elide: Text.ElideMiddle
                Layout.maximumWidth: root.width * 0.6
            }
        }
        Item {
            id: viewport
            Layout.fillWidth: true
            Layout.fillHeight: true
            EmptyState {
                anchors.centerIn: parent
                width: Math.min(parent.width, 460)
                visible: !root.hasImage
                onAddImages: root.addImages()
            }
            Item {
                id: frame
                objectName: "comparisonFrame"
                readonly property real aspect: root.controller.previewAspect
                anchors.centerIn: parent
                width: Math.max(1, Math.min(viewport.width, viewport.height * aspect))
                height: width / aspect
                visible: root.hasImage
                Accessible.role: Accessible.Graphic
                Accessible.name: qsTr("Image preview: %1").arg(root.controller.selectedName)
                Item {
                    id: resultClip
                    x: root.hasResult ? frame.width * split.value : 0
                    width: frame.width - x
                    height: frame.height
                    clip: true
                    Image {
                        id: resultImage
                        x: -resultClip.x
                        width: frame.width
                        height: frame.height
                        source: root.hasResult ? root.controller.resultUrl :
                                                 root.controller.originalPreviewUrl
                        sourceSize: Qt.size(2048, 2048)
                        asynchronous: true
                        autoTransform: true
                        fillMode: Image.PreserveAspectFit
                    }
                }
                Item {
                    width: frame.width * split.value
                    height: frame.height
                    clip: true
                    visible: root.hasResult
                    Image {
                        width: frame.width
                        height: frame.height
                        source: root.controller.originalPreviewUrl
                        sourceSize: Qt.size(2048, 2048)
                        asynchronous: true
                        autoTransform: true
                        fillMode: Image.PreserveAspectFit
                    }
                }
                Rectangle {
                    visible: root.hasResult && resultImage.status === Image.Ready
                    x: frame.width * split.value - 1
                    width: 2
                    height: frame.height
                    color: Theme.accent
                }
                BusyIndicator {
                    anchors.centerIn: parent
                    running: root.hasImage && resultImage.status === Image.Loading
                    visible: running
                }
                Label {
                    anchors.centerIn: parent
                    visible: resultImage.status === Image.Error
                    text: qsTr("This image preview could not be loaded.")
                    color: Theme.error
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: root.hasResult
            Label {
                text: qsTr("Original")
                color: Theme.muted
                font.pointSize: Theme.caption
            }
            Slider {
                id: split
                Layout.fillWidth: true
                from: 0
                to: 1
                value: 0.5
                Accessible.name: qsTr("Original and enhanced comparison")
            }
            Label {
                objectName: "resultScaleLabel"
                text: qsTr("Result · %1×").arg(Number(root.controller.resultScale).toLocaleString(
                                                   Qt.locale(), 'g', 3))
                color: Theme.accent
                font.pointSize: Theme.caption
            }
        }
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            visible: !root.hasResult
            spacing: 7
            Icon {
                name: "shield"
                implicitWidth: 16
                implicitHeight: 16
            }
            Label {
                text: qsTr("Your images stay on your device.")
                color: Theme.muted
                font.pointSize: Theme.caption
            }
        }
    }
}
