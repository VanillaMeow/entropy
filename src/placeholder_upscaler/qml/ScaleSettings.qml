import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Upscaler.Backend
import "components"

ColumnLayout {
    id: root
    required property AppController controller
    readonly property var presets: [25, 50, 75, 100, 150, 200, 300, 400]
    spacing: 12

    SectionLabel {
        text: qsTr("OUTPUT SIZE")
    }
    ComboBox {
        objectName: "scalePresets"
        Layout.fillWidth: true
        model: [qsTr("0.25× · 25%"), qsTr("0.5× · 50%"), qsTr("0.75× · 75%"), qsTr("1× · 100%"),
            qsTr("1.5× · 150%"), qsTr("2× · 200%"), qsTr("3× · 300%"), qsTr("4× · 400%")]
        currentIndex: root.presets.indexOf(Math.round(root.controller.outputScale * 100))
        displayText: currentIndex >= 0 ? currentText : qsTr("Custom size")
        enabled: root.controller.canEdit
        Accessible.name: qsTr("Output size preset")
        onActivated: root.controller.outputScale = root.presets[currentIndex] / 100
    }
    RowLayout {
        Layout.fillWidth: true
        Label {
            Layout.fillWidth: true
            text: qsTr("Scale (%)")
            color: Theme.text
            font.pointSize: Theme.body
        }
        SpinBox {
            objectName: "scalePercent"
            from: 10
            to: 400
            stepSize: 1
            value: Math.round(root.controller.outputScale * 100)
            editable: true
            enabled: root.controller.canEdit
            Accessible.name: qsTr("Output scale percent")
            onValueModified: root.controller.outputScale = value / 100
        }
    }
    Label {
        Layout.fillWidth: true
        text: {
            if (root.controller.outputScale < 1)
                return qsTr("Downscale with high-quality resizing. No GPU required.");
            if (root.controller.outputScale === 1)
                return qsTr("Keep original dimensions. No enhancement applied.");
            return qsTr("Enhance and resize to the selected size. 100% is the original size.");
        }
        color: Theme.muted
        font.pointSize: Theme.caption
        wrapMode: Text.WordWrap
    }
}
