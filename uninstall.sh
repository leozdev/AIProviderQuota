#!/usr/bin/env bash
set -euo pipefail
qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript '
var containers = desktops().concat(panels());
for (var i = 0; i < containers.length; i++) {
    var items = containers[i].widgets();
    for (var j = 0; j < items.length; j++) {
        if (items[j].type === "org.leoz.aiquotas") items[j].remove();
    }
}'
kpackagetool6 --type Plasma/Applet --remove org.leoz.aiquotas
echo 'Widget removido. A chave do Ollama foi preservada no KWallet (pasta AI Quotas).'
