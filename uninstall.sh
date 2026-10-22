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
        echo 'Aviso: não foi possível remover as instâncias pelo Plasma; o pacote será removido mesmo assim.' >&2
    fi
else
    echo 'Aviso: qdbus não encontrado; o pacote será removido sem acessar a sessão do Plasma.' >&2
fi
kpackagetool6 --type Plasma/Applet --remove org.leoz.aiquotas
echo 'Widget removido. A chave do Ollama foi preservada no KWallet (pasta AI Quotas).'
