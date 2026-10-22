pragma ComponentBehavior: Bound

import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as P5Support
import "lib.js" as Lib

// Executable-engine bridge adapted from PlasmaWidgetAiUsage (MIT).
PlasmoidItem {
    id: root
    Plasmoid.backgroundHints: PlasmaCore.Types.NoBackground
    property var report: null
    property bool loading: false
    property string lastError: ""
    property string currentSource: ""
    property string activeProviders: ""
    property bool pendingRefresh: false
    property bool pendingForce: false
    property int serial: 0
    property double nowMs: Date.now()
    readonly property int maxAge: 600
    readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("../code/quota_collector.py").toString().replace(/^file:\/\//, ""))
    readonly property string providers: [Plasmoid.configuration.showCodex ? "codex" : "", Plasmoid.configuration.showClaude ? "claude" : "", Plasmoid.configuration.showOllama ? "ollama" : ""].filter(function (p) {
        return p.length > 0;
    }).join(",")

    toolTipMainText: i18n("Cotas de IA · disponível")
    toolTipSubText: {
        if (!root.report)
            return root.loading ? i18n("Consultando…") : i18n("Aguardando consulta");
        return root.report.providers.map(function (p) {
            return Lib.providerSummary(p, root.nowMs, root.maxAge);
        }).join("\n");
    }

    function refresh(force) {
        if (root.loading) {
            root.pendingForce = root.pendingForce || force;
            root.pendingRefresh = root.pendingForce || root.providers !== root.activeProviders;
            return;
        }
        root.activeProviders = root.providers;
        root.loading = true;
        root.serial++;
        root.currentSource = "AI_QUOTAS_RUN=" + root.serial + " /usr/bin/python3 " + Lib.quote(root.helperPath) + " --providers " + Lib.quote(root.providers) + (force ? " --force" : "");
        watchdog.restart();
        executable.connectSource(root.currentSource);
    }

    function finishRefresh() {
        root.currentSource = "";
        root.loading = false;
        if (root.pendingRefresh) {
            const force = root.pendingForce;
            root.pendingRefresh = false;
            root.pendingForce = false;
            root.refresh(force);
        }
    }

    P5Support.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []
        onNewData: function (sourceName, data) {
            disconnectSource(sourceName);
            if (sourceName !== root.currentSource)
                return;
            watchdog.stop();
            try {
                const parsed = JSON.parse(data["stdout"] || "");
                if (parsed.schema_version !== 1 || !Array.isArray(parsed.providers))
                    throw new Error("schema");
                root.report = parsed;
                root.lastError = "";
            } catch (e) {
                root.lastError = i18n("Não foi possível atualizar. Tente novamente.");
            }
            root.finishRefresh();
        }
    }

    Timer {
        interval: Math.max(60, Plasmoid.configuration.refreshIntervalSec) * 1000
        running: true
        repeat: true
        onTriggered: root.refresh(false)
    }
    Timer {
        interval: 5000
        running: true
        repeat: true
        onTriggered: root.nowMs = Date.now()
    }
    Timer {
        id: watchdog
        interval: 30000
        onTriggered: {
            executable.disconnectSource(root.currentSource);
            root.lastError = i18n("A consulta demorou demais. Tente novamente.");
            root.finishRefresh();
        }
    }
    onProvidersChanged: Qt.callLater(function () {
        root.refresh(false);
    })
    Component.onCompleted: root.refresh(false)

    compactRepresentation: CompactRepresentation {
        report: root.report
        nowMs: root.nowMs
        maxAge: root.maxAge
        onClicked: root.expanded = !root.expanded
    }
    fullRepresentation: FullRepresentation {
        themeMode: Plasmoid.configuration.themeMode
        backgroundOpacity: Plasmoid.configuration.backgroundOpacity
        report: root.report
        loading: root.loading
        lastError: root.lastError
        nowMs: root.nowMs
        maxAge: root.maxAge
        onRefreshRequested: root.refresh(true)
    }
}
