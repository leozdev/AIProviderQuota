pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support
import "../lib.js" as Lib

KCM.SimpleKCM {
    id: page
    property alias cfg_title: titleField.text
    property alias cfg_titleAlignment: titleAlignment.currentIndex
    property alias cfg_bodyFontSize: fontSize.value
    property alias cfg_showProviderIcon: providerIcon.checked
    property alias cfg_showQuotaPeriod: quotaPeriod.checked
    property alias cfg_showProgressBar: progressBar.checked
    property alias cfg_showQuotaValue: quotaValue.checked
    property alias cfg_showResetTime: resetTime.checked
    property alias cfg_showCodex: codex.checked
    property alias cfg_showClaude: claude.checked
    property alias cfg_showOllama: ollama.checked
    property alias cfg_refreshIntervalSec: interval.value
    property alias cfg_themeMode: theme.currentIndex
    property alias cfg_backgroundOpacity: backgroundOpacitySlider.value
    property bool configuring: false
    property string walletResult: ""
    readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("../../code/quota_collector.py").toString().replace(/^file:\/\//, ""))

    Kirigami.FormLayout {
        QQC2.TextField {
            id: titleField
            Kirigami.FormData.label: i18n("Title:")
            placeholderText: i18n("AI Quotes")
            Layout.fillWidth: true
        }
        QQC2.ComboBox {
            id: titleAlignment
            Kirigami.FormData.label: i18n("Title alignment:")
            model: [i18n("Left"), i18n("Center"), i18n("Right"), i18n("Disabled")]
        }
        QQC2.SpinBox {
            id: fontSize
            Kirigami.FormData.label: i18n("Font size (pt):")
            from: 6
            to: 24
            editable: true
        }
        QQC2.Label {
            text: i18n("Sets the base size of the card's body text. It scales with the widget.")
            Layout.maximumWidth: 420
            wrapMode: Text.WordWrap
        }
        QQC2.CheckBox {
            id: providerIcon
            Kirigami.FormData.label: i18n("Card elements:")
            text: i18n("Provider icon")
        }
        QQC2.CheckBox {
            id: quotaPeriod
            text: i18n("Quota period (7d, 5h)")
        }
        QQC2.CheckBox {
            id: progressBar
            text: i18n("Progress bar")
        }
        QQC2.CheckBox {
            id: quotaValue
            text: i18n("Quota value (percentage or balance)")
        }
        QQC2.CheckBox {
            id: resetTime
            text: i18n("Time until reset")
        }
        QQC2.CheckBox {
            id: codex
            Kirigami.FormData.label: i18n("Providers:")
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
            Kirigami.FormData.label: i18n("Refresh every:")
            from: 60
            to: 900
            stepSize: 60
            textFromValue: function (value, locale) {
                return Number(value / 60).toLocaleString(locale, "f", 0) + " min";
            }
        }
        QQC2.ComboBox {
            id: theme
            Kirigami.FormData.label: i18n("Theme:")
            model: [i18n("Automatic (Plasma)"), i18n("Light"), i18n("Dark")]
        }
        RowLayout {
            Kirigami.FormData.label: i18n("Background opacity:")
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
            text: i18n("Codex and Claude reuse the existing client logins. The Ollama key is protected in KWallet.")
            Layout.maximumWidth: 420
            wrapMode: Text.WordWrap
        }
        QQC2.Button {
            text: i18n("Configure Ollama key…")
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
                page.walletResult = result.stored ? i18n("Key stored in KWallet. Refresh the widget to query your quota.") : (result.cancelled ? i18n("Configuration cancelled.") : result.message || i18n("Could not store the key."));
            } catch (e) {
                page.walletResult = i18n("Could not store the key.");
            }
        }
    }
}
