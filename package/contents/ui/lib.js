.pragma library

// Formatting/countdown pattern adapted from PlasmaWidgetAiUsage (MIT).
function colorFor(id) {
    if (id === "codex") return "#10a37f";
    if (id === "claude") return "#d97757";
    return "#6b8fd6";
}

function validProvider(provider, nowMs, maxAge) {
    if (!provider || !provider.fetched_at) return false;
    if (provider.state !== "ok" && provider.state !== "stale") return false;
    var age = nowMs / 1000 - provider.fetched_at;
    return age >= -30 && age <= maxAge;
}

function liveWindow(provider, window, nowMs, maxAge) {
    return validProvider(provider, nowMs, maxAge) && window
        && (!window.resets_at || window.resets_at * 1000 > nowMs);
}

function isStale(provider, nowMs, maxAge) {
    return provider.state === "stale"
        || !!(provider.fetched_at && !validProvider(provider, nowMs, maxAge));
}

function percent(value) {
    if (typeof value !== "number" || !isFinite(value)) return "—";
    return value.toLocaleString(Qt.locale("pt_BR"), "f", value % 1 === 0 ? 0 : 1) + "%";
}

function valueFor(provider, window, nowMs, maxAge) {
    if (!liveWindow(provider, window, nowMs, maxAge)) return "—";
    if (typeof window.remaining_usd === "number")
        return "US$ " + window.remaining_usd.toLocaleString(Qt.locale("pt_BR"), "f", 2);
    return percent(window.remaining_percent);
}

function headline(provider, nowMs, maxAge) {
    if (!validProvider(provider, nowMs, maxAge)) return null;
    var best = null;
    for (var i = 0; i < provider.windows.length; i++) {
        var window = provider.windows[i];
        if (!liveWindow(provider, window, nowMs, maxAge)) continue;
        if (!best || (typeof window.remaining_percent === "number"
            && (typeof best.remaining_percent !== "number"
                || window.remaining_percent < best.remaining_percent))) best = window;
    }
    return best;
}

function displayWindows(provider) {
    // Keep the same order for every provider, without inventing absent windows.
    function rank(window) {
        if (["7d", "seven_day", "weekly"].indexOf(window.key) >= 0) return 0;
        if (["5h", "five_hour", "session"].indexOf(window.key) >= 0) return 1;
        return 2;
    }
    return (provider.windows || []).slice().sort(function (a, b) {
        return rank(a) - rank(b);
    }).slice(0, 2);
}

function providerSummary(provider, nowMs, maxAge) {
    var window = headline(provider, nowMs, maxAge);
    return provider.label + ": " + (window
        ? window.label + " " + valueFor(provider, window, nowMs, maxAge)
        : provider.message || "Dados indisponíveis");
}

function providerTooltip(provider, windows, nowMs, maxAge) {
    function describe(window) {
        return window.label + ": " + valueFor(provider, window, nowMs, maxAge)
            + " disponível · " + countdown(window.resets_at, nowMs);
    }
    var lines = [provider.label + (isStale(provider, nowMs, maxAge) ? " · Dados antigos" : "")];
    for (var i = 0; i < windows.length; i++) lines.push(describe(windows[i]));
    var critical = headline(provider, nowMs, maxAge);
    if (critical && !windows.some(function (window) { return window.key === critical.key; }))
        lines.push("Mais restritiva: " + describe(critical));
    if (provider.message) lines.push(provider.message);
    return lines.join("\n");
}

function shortCountdown(epoch, nowMs) {
    if (!epoch || epoch * 1000 <= nowMs) return "—";
    var seconds = epoch - nowMs / 1000;
    if (seconds >= 604800) return Math.floor(seconds / 604800) + "w";
    if (seconds >= 86400) return Math.floor(seconds / 86400) + "d";
    if (seconds >= 3600) return Math.floor(seconds / 3600) + "h";
    return Math.max(1, Math.floor(seconds / 60)) + "m";
}

function shortWindowLabel(window) {
    if (["7d", "seven_day", "weekly"].indexOf(window.key) >= 0) return "7d";
    if (window.key === "five_hour") return "5h";
    if (window.key === "session") return "5h";
    if (window.key === "monthly") return "Mês";
    if (window.key === "purchased") return "Extra";
    return window.label;
}

function countdown(epoch, nowMs) {
    if (!epoch) return "Renovação não informada";
    var remaining = epoch - nowMs / 1000;
    if (remaining <= 0) return "Aguardando nova consulta";
    var days = Math.floor(remaining / 86400);
    var hours = Math.floor(remaining % 86400 / 3600);
    var minutes = Math.floor(remaining % 3600 / 60);
    if (days > 0) return "Renova em " + days + "d " + hours + "h";
    if (hours > 0) return "Renova em " + hours + "h " + minutes + "min";
    return "Renova em " + Math.max(1, minutes) + "min";
}

function ageLabel(epoch, nowMs) {
    if (!epoch) return "Aguardando consulta";
    var seconds = Math.max(0, nowMs / 1000 - epoch);
    if (seconds < 60) return "Atualizado agora";
    return "Atualizado há " + Math.floor(seconds / 60) + " min";
}

function attemptLabel(epoch, nowMs) {
    return ageLabel(epoch, nowMs).replace("Atualizado", "Consultado");
}

function quote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'";
}
