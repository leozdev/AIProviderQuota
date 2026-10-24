.pragma library

// Formatting/countdown pattern adapted from PlasmaWidgetAiUsage (MIT).
function colorFor(id) {
    if (id === "codex") return "#10a37f";
    if (id === "claude") return "#d97757";
    return "#6b8fd6";
}

function scaledFont(font, factor, weight) {
    var properties = {family: font.family, weight: weight === undefined ? font.weight : weight, italic: font.italic,
                      letterSpacing: font.letterSpacing, wordSpacing: font.wordSpacing};
    if (font.pointSize > 0) properties.pointSize = font.pointSize * factor;
    else properties.pixelSize = Math.max(1, Math.round(font.pixelSize * factor));
    return Qt.font(properties);
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
    return value.toLocaleString(Qt.locale(), "f", value % 1 === 0 ? 0 : 1) + "%";
}

function quotaValue(window) {
    if (typeof window.remaining_usd === "number")
        return "USD " + window.remaining_usd.toLocaleString(Qt.locale(), "f", 2);
    return percent(window.remaining_percent);
}

function valueFor(provider, window, nowMs, maxAge) {
    return liveWindow(provider, window, nowMs, maxAge) ? quotaValue(window) : "—";
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
        : provider.message || "Data unavailable");
}

function providerTooltip(provider, nowMs, maxAge) {
    var critical = headline(provider, nowMs, maxAge);
    var lines = [provider.label + " · Available" + (isStale(provider, nowMs, maxAge) ? " · Stale data" : "")];
    (provider.windows || []).forEach(function (window) {
        var label = window.key === "purchased" ? window.label : shortWindowLabel(window);
        lines.push(label + ": " + valueFor(provider, window, nowMs, maxAge)
            + " · " + countdown(window.resets_at, nowMs)
            + (window.resets_at ? " (" + Qt.formatDateTime(new Date(window.resets_at * 1000), "dd MMM, HH:mm") + ")" : ""));
    });
    if (critical && !displayWindows(provider).some(function (window) { return window.key === critical.key; }))
        lines.push("Most restrictive: " + critical.label);
    if (provider.message) lines.push(provider.message);
    lines.push((provider.source ? provider.source + " · " : "") + ageLabel(provider.fetched_at, nowMs));
    return lines.join("\n");
}

function shortDuration(seconds) {
    if (seconds >= 604800) return Math.floor(seconds / 604800) + "w";
    if (seconds >= 86400) return Math.floor(seconds / 86400) + "d";
    if (seconds >= 3600) return Math.floor(seconds / 3600) + "h";
    return Math.max(1, Math.floor(seconds / 60)) + "m";
}

function shortCountdown(epoch, nowMs) {
    if (!epoch || epoch * 1000 <= nowMs) return "—";
    return shortDuration(epoch - nowMs / 1000);
}

function shortWindowLabel(window) {
    if (["7d", "seven_day", "weekly"].indexOf(window.key) >= 0) return "7d";
    if (["5h", "five_hour", "session"].indexOf(window.key) >= 0) return "5h";
    if (window.key === "monthly") return "mo";
    if (window.key === "purchased") return "Extra";
    return window.label;
}

function countdown(epoch, nowMs) {
    if (!epoch) return "Reset time unavailable";
    var remaining = epoch - nowMs / 1000;
    if (remaining <= 0) return "Waiting for a new query";
    return "Resets in " + shortDuration(remaining);
}

function validTimestamp(epoch) {
    return typeof epoch === "number" && isFinite(epoch) && epoch > 0;
}

function oldestTimestamp(report) {
    var oldest = null;
    (report ? report.providers : []).forEach(function (provider) {
        var epoch = provider.fetched_at;
        if (validTimestamp(epoch) && (oldest === null || epoch < oldest)) oldest = epoch;
    });
    return oldest;
}

function shortAge(epoch, nowMs) {
    if (!validTimestamp(epoch)) return "—";
    var seconds = Math.max(0, nowMs / 1000 - epoch);
    return seconds < 60 ? "Now" : shortDuration(seconds);
}

function nextAgeInterval(epoch, nowMs) {
    var referenceMs = epoch * 1000;
    var minutes = Math.floor(Math.max(0, nowMs - referenceMs) / 60000);
    return Math.max(1, Math.min(60000, Math.ceil(referenceMs + (minutes + 1) * 60000 - nowMs)));
}

function ageLabel(epoch, nowMs) {
    if (!validTimestamp(epoch)) return "Waiting for a query";
    var age = shortAge(epoch, nowMs);
    return age === "Now" ? "Updated now" : "Updated " + age + " ago";
}

function attemptLabel(epoch, nowMs) {
    return validTimestamp(epoch) ? "Last attempt: " + shortAge(epoch, nowMs) : "No query yet";
}

function footerTooltip(report, nowMs, maxAge) {
    var lines = ["Oldest data: " + shortAge(oldestTimestamp(report), nowMs),
                 "Cached or local-session data keeps its original timestamp."];
    (report ? report.providers : []).forEach(function (provider) {
        if (isStale(provider, nowMs, maxAge) || !validProvider(provider, nowMs, maxAge))
            lines.push(provider.label + ": " + (provider.message || "Data unavailable or stale"));
    });
    return lines.join("\n");
}

function quote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'";
}
