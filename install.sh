#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if kpackagetool6 --type Plasma/Applet --show org.leoz.aiquotas >/dev/null 2>&1; then
    kpackagetool6 --type Plasma/Applet --upgrade "$project_dir/package"
else
    kpackagetool6 --type Plasma/Applet --install "$project_dir/package"
fi
echo 'Cotas de IA instalado para este usuário. Adicione-o à área de trabalho ou ao painel pelo menu Adicionar widgets.'
