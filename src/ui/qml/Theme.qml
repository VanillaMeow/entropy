pragma Singleton
import QtQuick

QtObject {
    property bool dark: true
    readonly property color background: dark ? "#111216" : "#f5f5f9"
    readonly property color surface: dark ? "#191a20" : "#ffffff"
    readonly property color raised: dark ? "#23242d" : "#ededf4"
    readonly property color outline: dark ? "#34353f" : "#dcdce7"
    readonly property color text: dark ? "#f0f0f5" : "#20212b"
    readonly property color muted: dark ? "#a9aab9" : "#636478"
    readonly property color accent: dark ? "#baaaff" : "#6246c7"
    readonly property color onAccent: dark ? "#24164a" : "#ffffff"
    readonly property color accentSurface: dark ? "#302741" : "#eee8ff"
    readonly property color success: dark ? "#9cd5bb" : "#246c4d"
    readonly property color error: dark ? "#ffb4b4" : "#ac263d"
    property real body: 12
    readonly property real caption: body / 1.2
    readonly property real heading: body * 1.44
    readonly property real title: body * 2.0736
}
