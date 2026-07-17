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
    // A null activation is how Plasma can represent a desktop/background
    // click. It is external too; the app ignores the signal when no popup is
    // visible.
    if (!client || !identifyTextPik(client)) {
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

// KWin 6 renamed the client-oriented API to window-oriented signals. Keep the
// guarded legacy branch so the same package remains usable on Plasma 5.
if (workspace.cursorPosChanged) {
    workspace.cursorPosChanged.connect(sendCursorPos);
}
if (workspace.windowActivated) {
    workspace.windowActivated.connect(onClientActivated);
} else if (workspace.clientActivated) {
    workspace.clientActivated.connect(onClientActivated);
}
if (workspace.windowAdded) {
    workspace.windowAdded.connect(keepTextPikOutOfTaskManager);
} else if (workspace.clientAdded) {
    workspace.clientAdded.connect(keepTextPikOutOfTaskManager);
}
const existingWindows = workspace.stackingOrder ||
    (workspace.windowList ? workspace.windowList() :
        (workspace.clientList ? workspace.clientList() : []));
if (existingWindows && existingWindows.forEach) {
    existingWindows.forEach(keepTextPikOutOfTaskManager);
}
sendCursorPos();
if (typeof setInterval === "function") {
    setInterval(sendCursorPos, 1000);
}
print("TextPik cursor bridge loaded");
