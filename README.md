# AIProviderQuota

**English** | [Português](README.pt-BR.md)

A compact **KDE Plasma 6** widget that brings together the available quotas for **Codex**, **Claude**, and **Ollama Cloud**.

| Light | Dark |
| --- | --- |
| ![Light theme](docs/images/light.png) | ![Dark theme](docs/images/themes.png) |

*Preview with sample data. Both themes use 82% background opacity.*

## Features

- A vertical list with provider icons, remaining-quota bars, and time until reset.
- Bars keep each provider's color at every quota level.
- Up to two windows per provider: `7d` and `5h`, when available. Ollama's session is labeled `5h`.
- Reset countdowns use a single unit: `1w`, `4d`, `2h`, or `30m`.
- Automatic, light, and dark themes, with background opacity adjustable from 0 to 100%.
- A responsive card without scrolling. Rows fill the available space; text and icons scale up while preserving a readable minimum.
- A custom title with Left, Center, Right, or Disabled alignment. Disabling the title removes its space.
- Compact provider tooltips with short periods and reset dates, available by hover and keyboard focus.
- A footer with the refresh button on the right and the age of the oldest data immediately beside it.
- Automatic refresh every two minutes, configurable from 1 to 15 minutes.
- A compact panel view with distinct icons and screen-reader-accessible provider names and values.

The widget tracks **provider subscriptions and tools**. Each bar shows the **remaining** percentage of the quota window reported by the account. Ollama accounts with a monthly dollar allowance are also supported, with purchased credits shown separately.
When an account only reports a dollar balance, the value is displayed without a percentage bar.

## Requirements

- Linux with KDE Plasma 6 and Qt 6. Validated on CachyOS, Plasma 6.8, and Wayland.
- Python 3, `kpackagetool6`, and `qdbus6`.
- Codex CLI and Claude Code already signed in, to track those providers.
- KWallet, `kwallet-query`, and an Ollama Cloud API key, to track Ollama.
- `kdialog` to configure the key through the UI; the Python `dbus` module to create the KWallet folder initially.

On CachyOS/Arch, `kpackagetool6`, `qdbus6`, `kwallet-query`, and `kdialog` are provided by the `kpackage`, `qt6-tools`, `kwallet`, and `kdialog` packages, respectively. The `dbus` module comes from `python-dbus`.

## Installation

```bash
git clone https://github.com/leozdev/AIProviderQuota.git
cd AIProviderQuota
bash install.sh
```

Open Plasma's widget picker, search for **AI Quotes**, and add it to your desktop or panel.

The installer uses the package in `package/` and installs it for the current user only, without `sudo`. An existing installation is upgraded. The script does not install or update system packages.

### Updating

```bash
git pull --ff-only
bash install.sh
```

If the widget is already loaded, Plasma may keep the previous QML in memory. Reload `plasmashell`, or sign out and back in, to load the updated interface. The installer does not restart Plasma automatically.

The new UI and newly collected messages use English. Some text from an older cached report can remain in Portuguese until that report is replaced; the update does not clear the cache or force extra provider requests.

## Accounts and quota sources

| Provider | Authentication and source |
| --- | --- |
| Codex | Reuses the local client's login and queries `account/rateLimits/read` through `codex app-server`. May fall back to a recent session log, identified as such. |
| Claude | Reuses Claude Code's OAuth credentials and queries `https://api.anthropic.com/api/oauth/usage`. **This is an internal endpoint and may change.** Claude Code remains responsible for renewing the login. |
| Ollama Cloud | Queries `https://ollama.com/api/balance` with a key stored in KWallet. |

To configure Ollama, right-click the widget, open its settings, and use the Ollama key configuration button on the general settings page. Enter the key in the KDE password dialog.

The key is stored in the default network wallet, under the `AI Quotas` folder and the `ollama-cloud-api-key` entry. You can also configure it from the terminal using interactive input:

```bash
python3 package/contents/code/quota_collector.py --configure-ollama

# To replace an existing key:
python3 package/contents/code/quota_collector.py --configure-ollama --replace
```

If the wallet is locked, the widget reports that it needs to be unlocked. Automatic refresh does not repeatedly open a password prompt.

## Appearance and usage

Use the settings to choose providers, refresh interval, theme, and background opacity. By default, the widget follows Plasma's colors and uses **82% opacity**. The background has no border, including at 0% opacity. Transparency affects the background; text and icons remain crisp. The compact panel view follows the panel's own colors.

- Hover over a provider or focus it with Tab to see every quota window, abbreviated local reset dates and times, source, collection age, and status. Provider rows do not expand when clicked.
- Set the title and its alignment in the widget settings. A blank title uses **AI Quotes**. Your custom text is preserved when the title is disabled.
- Set **Font size (pt)** for the card's body text and provider tooltips, from 6 to 24 pt (default: **8 pt**). The card scales this base size to fit; tooltips use the base size directly. The title keeps its Plasma font.
- Under **Card elements**, independently show or hide the provider icon, quota period, progress bar, quota value, and reset countdown. All five are enabled by default. The value shows remaining quota (percentage or balance). These options apply to the full card; complete details remain in the provider tooltips.
- The footer shows **Now** for data younger than a minute, then `1m`, `2m`, `1h`, `1d`, or `1w`. It updates at the data's minute boundaries, independently of provider queries. It uses the oldest provider timestamp, so cached data or a partial failure can keep an older age after refresh. If no timestamp is available, it shows `—`.
- Use the refresh button to request a new query.
- In the panel, each provider's indicator shows the window with the lowest remaining percentage.
- If that window is not among the two visible bars, the tooltip identifies the most restrictive quota. The tooltip shows every returned window.

The custom title applies to the full card; the panel indicator keeps the default name. Text is in English, while numbers and dates follow your system locale.

If you change the selected providers during a query, the new selection is collected as soon as the current query finishes.

## Failures and privacy

Quota collection does not send prompts to models. Each provider has its own state; HTTP 429 responses respect the wait time specified by the provider. Collection has a total deadline of 20 seconds, preserving completed results if another provider takes too long. Concurrent instances wait for the active collection and reuse its recent cache within the same deadline.

During a temporary failure, the last valid value may remain visible for up to ten minutes, marked as stale and retaining its original timestamp. Once a quota window reaches its reset time, its percentage is hidden until a new valid response arrives. Rejected authentication from Claude or Ollama invalidates that provider's cached values.

For Codex, RPC errors do not distinguish authentication rejection from other failures: the collector may use a recent local session log, identified as such, or a cache marked as stale. These values also expire after ten minutes and do not confirm that the login is still active.

The cache is stored in `~/.cache/ai-quotas/` and contains quotas and timestamps. Tokens and the Ollama key are not included in these reports. Codex and Claude credentials remain under their respective clients' control; the Ollama key is read from KWallet.

## Development and validation

The Python collector uses the standard library for normal collection and returns normalized JSON to QML. The UI lives in `package/contents/ui/`, and the collector is in `package/contents/code/quota_collector.py`. The version sent to quota sources comes from `package/metadata.json`.

Unit tests use simulated responses and do not require accounts:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

To check QML, use `qmllint` from your Qt 6 installation:

```bash
/usr/lib/qt6/bin/qmllint package/contents/ui/*.qml \
  package/contents/ui/config/*.qml package/contents/config/config.qml
```

Optional graphical tests require KWin, PySide6, Pillow, Spectacle, and `dbus-run-session`, as well as Plasma. They create an isolated Wayland session without replacing your compositor:

```bash
# Render with sample data, without querying accounts:
python3 tests/run_wayland_validation.py

# Native integration and changes during a query, with sample data:
python3 tests/run_wayland_validation.py --plasma-fixture

# Native integration: queries local accounts and accesses KWallet:
python3 tests/run_wayland_validation.py --plasma
```

Results are written to `evidence/`, which is ignored by Git. The visual test uses the public `tests/fixtures/quota-demo.json` fixture; service availability is recorded separately from UI checks in the native test. Automated checks cover timing, geometry, focus, accessible descriptions, settings roundtrips, and right-click propagation to a test host. Native menu interaction, the Apply/Cancel dialog flow, and actual screen-reader output require separate manual verification.

## Uninstalling

```bash
bash uninstall.sh
```

The script removes instances of the widget and its installed package. If it cannot access the Plasma session, it reports this and continues removing the package. The Ollama key is preserved in KWallet. To delete it, use the wallet manager to remove the entry described above. The cache can be removed separately from `~/.cache/ai-quotas/`.

## Limitations

- Available quota windows depend on the account and the provider's response.
- Claude's endpoint is internal; service changes may require integration updates.
- Antigravity/Gemini support is planned for a future stage.

## Authorship, license, and credits

**AIProviderQuota is developed and maintained by [Leo Zamparo (leozdev)](https://github.com/leozdev).**

Leo Zamparo's 2026 copyright covers AIProviderQuota's additions and adaptations. Marc Cheng's original copyright notice and the MIT license text for the reused code are preserved in `LICENSE` and `package/LICENSE`.

Code is released under the [MIT license](LICENSE). The QML/Python integration and parts of the Codex protocol were adapted from [PlasmaWidgetAiUsage](https://github.com/WariKoda/PlasmaWidgetAiUsage) by Marc Cheng, revision `1b8fef4f2ca78482d8ca289a4204f02e5c51e111`. Marc is credited as the author of that reused code. See [NOTICE](NOTICE) for provenance details.

Icon provenance is documented in [ATTRIBUTION.md](package/contents/icons/ATTRIBUTION.md). Trademarks belong to their respective providers.
