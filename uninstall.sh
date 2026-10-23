#!/usr/bin/env bash
set -euo pipefail
dbus_command="$(command -v qdbus6 || true)"
if [[ -z "$dbus_command" && -x /usr/lib/qt6/bin/qdbus ]]; then
    dbus_command=/usr/lib/qt6/bin/qdbus
fi
if [[ -n "$dbus_command" ]]; then
    if ! "$dbus_command" org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript '
var containers = desktops().concat(panels());
for (var i = 0; i < containers.length; i++) {
    var items = containers[i].widgets();
    for (var j = 0; j < items.length; j++) {
        if (items[j].type === "org.leoz.aiquotas") items[j].remove();
    }
}'; then
        echo 'Warning: could not remove widget instances through Plasma; the package will still be removed.' >&2
    fi
else
    echo 'Warning: qdbus was not found; the package will be removed without accessing the Plasma session.' >&2
fi
kpackagetool6 --type Plasma/Applet --remove org.leoz.aiquotas
echo 'Widget removed. The Ollama key was preserved in KWallet (AI Quotas folder).'
