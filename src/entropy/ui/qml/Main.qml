pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import Entropy

ApplicationWindow {
    id: root
    required property AppController controller
    property bool settingsOpen: false
    property bool diagnosticsOpen: false
    readonly property bool wide: width >= 1060
    width: 1320
    height: 880
    minimumWidth: 760
    minimumHeight: 680
    visible: true
    title: qsTr("Entropy v%1").arg(Qt.application.version)
    color: Theme.background
    font.pointSize: Theme.body
    Material.theme: controller.darkTheme ? Material.Dark : Material.Light
    Material.accent: Theme.accent
    Material.primary: Theme.surface
    Binding {
        target: Theme
        property: "dark"
        value: root.controller.darkTheme
    }
    Binding {
        target: Theme
        property: "body"
        value: root.controller.bodyFontSize
    }
    header: HeaderBar {
        controller: root.controller
        compact: !root.wide
        onAddImages: pickers.choose("images")
        onAddFolder: pickers.choose("inputFolder")
        onSettingsRequested: root.settingsOpen = true
        onDiagnosticsRequested: root.diagnosticsOpen = true
    }
    Workspace {
        anchors.fill: parent
        controller: root.controller
        wide: root.wide
        onAddImages: pickers.choose("images")
        onAddFolder: pickers.choose("inputFolder")
        onChooseOutput: pickers.choose("outputFolder")
    }
    footer: StatusBar {
        controller: root.controller
    }
    FilePickers {
        id: pickers
        controller: root.controller
    }
    Loader {
        active: root.settingsOpen && !root.wide
        sourceComponent: SettingsDrawer {
            controller: root.controller
            onClosed: root.settingsOpen = false
            onChooseOutput: pickers.choose("outputFolder")
        }
        onLoaded: {
            const drawer = item as SettingsDrawer;
            if (status === Loader.Ready && drawer)
                drawer.open();
        }
    }
    Loader {
        active: root.diagnosticsOpen
        sourceComponent: DiagnosticsDrawer {
            controller: root.controller
            onClosed: root.diagnosticsOpen = false
        }
        onLoaded: {
            const drawer = item as DiagnosticsDrawer;
            if (status === Loader.Ready && drawer)
                drawer.open();
        }
    }
    Shortcut {
        sequences: [StandardKey.Open]
        enabled: root.controller.canEdit
        onActivated: pickers.choose("images")
    }
    onClosing: controller.shutdown()
}
