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

function onWindowActivated(window) {
    // This signal proves a KWin activation change, not a raw global mouse
    // click. TextPik keeps those two capabilities separate.
    if (!window || !identifyTextPik(window)) {
        callDBus(
            service,
            path,
            iface,
            "notifyWindowActivated"
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
    workspace.windowActivated.connect(onWindowActivated);
} else if (workspace.clientActivated) {
    workspace.clientActivated.connect(onWindowActivated);
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
print("TextPik cursor/activation bridge loaded");
