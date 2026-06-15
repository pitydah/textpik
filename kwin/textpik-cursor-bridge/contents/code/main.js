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

workspace.cursorPosChanged.connect(sendCursorPos);
workspace.clientActivated.connect(onClientActivated);
sendCursorPos();
if (typeof setInterval === "function") {
    setInterval(sendCursorPos, 1000);
}
print("TextPik cursor bridge loaded");
