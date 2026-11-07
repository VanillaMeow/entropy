import QtQuick
import ".."

Item {
    id: root
    property string name: "image"
    property color color: Theme.muted
    readonly property var paths: ({
                                      "add": "M12 5v14M5 12h14",
                                      "folder": "M3 7v12h18V7h-9l-2-3H3v3z",
                                      "arrow": "M5 12h14m-6-6 6 6-6 6",
                                      "upload": "M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5",
                                      "image": "M3 3h18v18H3zM3 17l6-6 5 5 3-3 4 4M8 7h.01",
                                      "trash": "M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7",
                                      "check": "m5 12 4 4L19 6",
                                      "shield": "M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3zm-4 9 3 3 5-6",
                                      "settings": "M4 7h16M4 17h16M8 4v6m8 4v6",
                                      "refresh":
                                      "M20 7v5h-5M4 17v-5h5m-5 0a8 8 0 0 1 14-5l2 5M4 12l2 5a8 8 0 0 0 14-5",
                                      "sun": "M12 2v2m0 16v2M2 12h2m16 0h2M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
                                      "moon": "M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11z",
                                      "info": "M12 11v6m0-10h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
                                      "close": "m6 6 12 12M6 18 18 6",
                                      "expand": "M4 10V4h6m4 0h6v6M4 14v6h6m4 0h6v-6"
                                  })
    implicitWidth: 20
    implicitHeight: 20
    Image {
        anchors.fill: parent
        sourceSize: Qt.size(24, 24)
        source: "data:image/svg+xml," + encodeURIComponent(
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="'
                    + root.color
                    + '" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="'
                    + (root.paths[root.name] || root.paths.image) + '"/></svg>')
    }
    Accessible.ignored: true
}
