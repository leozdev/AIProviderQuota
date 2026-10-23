#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if kpackagetool6 --type Plasma/Applet --show org.leoz.aiquotas >/dev/null 2>&1; then
    kpackagetool6 --type Plasma/Applet --upgrade "$project_dir/package"
else
    kpackagetool6 --type Plasma/Applet --install "$project_dir/package"
fi
echo 'AI Quotes installed for the current user. Add it to the desktop or panel using Add Widgets.'
