const service = "org.textpik.CursorBridge";
const path = "/Cursor";
const iface = "org.textpik.CursorBridge";

function sendCursorPos() {
    const pos = workspace.cursorPos;
    if (!pos) {
        return;
    }
    callDBus(
        service,
        path,
        iface,
        "updateCursor",
        Math.round(pos.x),
        Math.round(pos.y)
    );
}

function onClientActivated(client) {
    // Cuando el usuario activa otra ventana (clic fuera del popup),
    // notificamos a TextPik para que cierre el popup.
    // El popup de TextPik es override-redirect, no aparece como client.
    if (client) {
        callDBus(
            service,
            path,
            iface,
            "notifyClickOutside"
        );
    }
}

function identifyTextPik(window) {
    if (!window) {
        return false;
    }
    const caption = String(window.caption || "").toLowerCase();
    const resourceClass = String(window.resourceClass || "").toLowerCase();
    const resourceName = String(window.resourceName || "").toLowerCase();
    return caption === "textpik" || resourceClass === "textpik" || resourceName === "textpik";
}

function keepTextPikOutOfTaskManager(window) {
    if (!identifyTextPik(window)) {
        return;
    }
    window.skipTaskbar = true;
    window.skipSwitcher = true;
    window.keepAbove = true;
}

workspace.cursorPosChanged.connect(sendCursorPos);
workspace.clientActivated.connect(onClientActivated);
if (workspace.windowAdded) {
    workspace.windowAdded.connect(keepTextPikOutOfTaskManager);
}
if (workspace.windowList) {
    workspace.windowList().forEach(keepTextPikOutOfTaskManager);
}
sendCursorPos();
if (typeof setInterval === "function") {
    setInterval(sendCursorPos, 1000);
}
print("TextPik cursor bridge loaded");
