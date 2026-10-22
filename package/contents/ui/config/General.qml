pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support
import "../lib.js" as Lib

Kirigami.FormLayout {
    id: page
    property alias cfg_showCodex: codex.checked
    property alias cfg_showClaude: claude.checked
    property alias cfg_showOllama: ollama.checked
    property alias cfg_refreshIntervalSec: interval.value
    property alias cfg_themeMode: theme.currentIndex
    property alias cfg_backgroundOpacity: backgroundOpacitySlider.value
    property bool configuring: false
    property string walletResult: ""
    readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("../../code/quota_collector.py").toString().replace(/^file:\/\//, ""))

    QQC2.CheckBox {
        id: codex
        Kirigami.FormData.label: i18n("Provedores:")
        text: i18n("Codex")
    }
    QQC2.CheckBox {
        id: claude
        text: i18n("Claude")
    }
    QQC2.CheckBox {
        id: ollama
        text: i18n("Ollama Cloud")
    }
    QQC2.SpinBox {
        id: interval
        Kirigami.FormData.label: i18n("Atualizar a cada:")
        from: 60
        to: 900
        stepSize: 60
        textFromValue: function (value, locale) {
            return Number(value / 60).toLocaleString(locale, "f", 0) + " min";
        }
    }
    QQC2.ComboBox {
        id: theme
        Kirigami.FormData.label: i18n("Tema:")
        model: [i18n("Automático (Plasma)"), i18n("Claro"), i18n("Escuro")]
    }
    RowLayout {
        Kirigami.FormData.label: i18n("Opacidade do fundo:")
        QQC2.Slider {
            id: backgroundOpacitySlider
            from: 0
            to: 100
            stepSize: 1
            snapMode: QQC2.Slider.SnapAlways
            Layout.preferredWidth: 180
        }
        QQC2.Label {
            text: Math.round(backgroundOpacitySlider.value) + "%"
            Layout.preferredWidth: 40
        }
    }
    QQC2.Label {
        text: i18n("Codex e Claude usam os logins existentes dos clientes. A chave do Ollama fica protegida no KWallet.")
        Layout.maximumWidth: 420
        wrapMode: Text.WordWrap
    }
    QQC2.Button {
        text: i18n("Configurar chave do Ollama…")
        icon.name: "wallet-open"
        enabled: !page.configuring
        onClicked: {
            page.configuring = true;
            page.walletResult = "";
            walletExec.connectSource("/usr/bin/python3 " + Lib.quote(page.helperPath) + " --configure-ollama --gui --replace");
        }
    }
    QQC2.Label {
        text: page.walletResult
        visible: text.length > 0
        Layout.maximumWidth: 420
        wrapMode: Text.WordWrap
    }
    P5Support.DataSource {
        id: walletExec
        engine: "executable"
        connectedSources: []
        onNewData: function (sourceName, data) {
            disconnectSource(sourceName);
            page.configuring = false;
            try {
                const result = JSON.parse(data["stdout"] || "");
                page.walletResult = result.stored ? i18n("Chave guardada no KWallet. Atualize o widget para consultar.") : (result.cancelled ? i18n("Configuração cancelada.") : result.message || i18n("Não foi possível guardar a chave."));
            } catch (e) {
                page.walletResult = i18n("Não foi possível guardar a chave.");
            }
        }
    }
}
