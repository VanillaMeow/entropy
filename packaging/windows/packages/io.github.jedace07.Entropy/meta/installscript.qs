function Component() {}

Component.prototype.createOperations = function() {
    component.createOperations();
    component.addOperation("CreateShortcut", "@TargetDir@/app/Entropy.exe",
        "@StartMenuDir@/Entropy.lnk", "workingDirectory=@TargetDir@/app",
        "iconPath=@TargetDir@/app/Entropy.ico", "description=Entropy image upscaler");
    component.addOperation("CreateShortcut", "@TargetDir@/app/Entropy.exe",
        "@DesktopDir@/Entropy.lnk", "workingDirectory=@TargetDir@/app",
        "iconPath=@TargetDir@/app/Entropy.ico", "description=Entropy image upscaler");
    component.addOperation("CreateShortcut", "@TargetDir@/EntropyMaintenanceTool.exe",
        "@StartMenuDir@/Uninstall Entropy.lnk", "workingDirectory=@TargetDir@",
        "arguments=--start-uninstaller", "description=Uninstall Entropy");
};
