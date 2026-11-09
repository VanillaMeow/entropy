function Controller() {
    installer.setDefaultPageVisible(QInstaller.ComponentSelection, false);
    installer.setDefaultPageVisible(QInstaller.StartMenuSelection, false);
    if (installer.isInstaller()) {
        var localAppData = installer.environmentVariable("LOCALAPPDATA");
        if (localAppData)
            installer.setValue("TargetDir", localAppData + "/Programs/Entropy");
    } else {
        installer.setUninstaller();
    }
}
