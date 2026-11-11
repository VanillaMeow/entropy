pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Dialogs
import Upscaler.Backend

Item {
    id: root
    objectName: "filePickers"
    required property AppController controller
    property string purpose: ""
    function choose(kind: string): void {
        if (controller.canEdit && purpose === "")
            purpose = kind;
    }
    Loader {
        id: picker
        active: root.purpose !== ""
        sourceComponent: root.purpose === "" ? null : root.purpose === "images" ? imagePicker :
                                                                                  folderPicker
        onLoaded: {
            if (status !== Loader.Ready)
                return;
            const files = item as FileDialog;
            const folder = item as FolderDialog;
            if (files)
                files.open();
            else if (folder)
                folder.open();
        }
    }
    Component {
        id: imagePicker
        FileDialog {
            title: qsTr("Choose images to upscale")
            fileMode: FileDialog.OpenFiles
            nameFilters: [qsTr("Images (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp)")]
            onAccepted: {
                root.controller.addUrls(selectedFiles);
                root.purpose = "";
            }
            onRejected: root.purpose = ""
        }
    }
    Component {
        id: folderPicker
        FolderDialog {
            title: root.purpose === "outputFolder" ? qsTr("Choose output folder") : qsTr(
                                                         "Add images from a folder")
            currentFolder: root.controller.outputUrl
            onAccepted: {
                if (root.purpose === "outputFolder")
                    root.controller.setOutputFolder(selectedFolder);
                else
                    root.controller.addUrls([selectedFolder]);
                root.purpose = "";
            }
            onRejected: root.purpose = ""
        }
    }
}
