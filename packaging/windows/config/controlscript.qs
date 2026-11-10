function Controller() {
    installer.setDefaultPageVisible(QInstaller.ComponentSelection, false);
    installer.setDefaultPageVisible(QInstaller.StartMenuSelection, false);
    if (installer.isInstaller()) {
        var localAppData = installer.environmentVariable("LOCALAPPDATA");
        if (localAppData)
            installer.setValue("TargetDir", localAppData + "/Programs/Entropy");
    } else {
        installer.setUninstaller();
        installer.setCompleteUninstallation(true);
        installer.setDefaultPageVisible(QInstaller.Introduction, false);
        installer.setDefaultPageVisible(QInstaller.LicenseCheck, false);
    }
}
