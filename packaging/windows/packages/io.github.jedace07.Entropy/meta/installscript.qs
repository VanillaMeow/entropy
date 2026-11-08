function Component() {}

Component.prototype.createOperations = function() {
    component.createOperations();
    component.addOperation("CreateShortcut", "@TargetDir@/Entropy.exe",
        "@StartMenuDir@/Entropy.lnk", "workingDirectory=@TargetDir@",
        "iconPath=@TargetDir@/Entropy.ico", "description=Entropy image upscaler");
    component.addOperation("CreateShortcut", "@TargetDir@/Entropy.exe",
        "@DesktopDir@/Entropy.lnk", "workingDirectory=@TargetDir@",
        "iconPath=@TargetDir@/Entropy.ico", "description=Entropy image upscaler");
    component.addOperation("CreateShortcut", "@TargetDir@/EntropyMaintenanceTool.exe",
        "@StartMenuDir@/Uninstall Entropy.lnk", "workingDirectory=@TargetDir@",
        "description=Maintain or uninstall Entropy");
};
