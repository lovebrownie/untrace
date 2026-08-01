# Untrace

<p align="center">
  <img src="assets/icon.svg" alt="untrace" width="128" height="128">
</p>

Untrace makes Chrome automation harder to detect. Install once, then use normal Chrome or bare Selenium — no per-script options, no test-side hacks.

Three independent layers (bare `--install` enables all):

| Layer | Flag | What it does |
|-------|------|-------------|
| **Stealth extension** | `--stealth-extension` | MV3 extension — injects anti-detection scripts at `document_start` in the `MAIN` world on every frame. **Linux:** local pack/seed. **Windows:** [Chrome Web Store force-install](https://chromewebstore.google.com/detail/untrace-injector/mgnlenokophofdnmlabkgpmlnolgomgj) |
| **Chrome launch wrapper** / **Random profiles** | `--launch-wrapper` | Replaces Chrome with a launch wrapper in front of `chrome_real` (bash on Linux, C# on Windows). Strips chromedriver junk flags, applies launcher flags, and uses a fresh random profile each launch. Seeds the extension into profiles on Linux; on Windows profiles live under `%TEMP%\chrome_random_profiles` |
| **Chromedriver CDC patch** | `--chromedriver-cdc` | Neutralizes the CDC (`window.cdc_*`) injection in cached chromedriver binaries and blanks `test-type=webdriver`. On Linux also blanks `enable-automation` and patches selenium-manager so `webdriver.Chrome()` picks up the wrapper. On Windows leaves `enable-automation` intact (required for remote debugging) |

## Quick start

### Linux

**Option A — `.deb` (GUI + `untrace` on `PATH`)**

```bash
uv run python scripts/build_gui.py   # or: uv run python -m untrace --build
sudo apt install ./dist/untrace_*_amd64.deb

untrace              # opens the GUI (on PATH)
untrace --status
untrace --gui
```

Remove the package (does not undo Chrome patches — run Uninstall in the GUI or `sudo untrace --uninstall` first):

```bash
sudo apt remove untrace
```

**Option B — from source (needs root)**

```bash
sudo python3 -m untrace --install --stealth-extension --launch-wrapper --chromedriver-cdc
python3 -m untrace --status
sudo python3 -m untrace --uninstall
```

```
OK Stealth extension
OK Random profiles
OK Chrome launch wrapper
OK Chromedriver CDC patch
OK Selenium-manager redirect
```

`--uninstall` restores system Chrome, deletes `/etc/untrace` and `~/.local/share/untrace` (via `SUDO_USER`), and unpatches chromedrivers / selenium-manager.

### Windows

**Option A — Setup installer (GUI + `untrace` on `PATH`)**

```powershell
uv run python scripts/build_gui.py
# dist\Untrace-*-Portable.exe     portable (Admin UAC)
# dist\Untrace-*-Setup.exe        installer (embeds VC++ + Inno Setup 6)
# dist\Untrace-*-Windows.zip      Setup + Portable + INSTRUCTIONS.txt
untrace              # after Setup: on PATH
untrace --status
untrace --gui
```

Uninstall from Windows Settings → Apps, or Start Menu → Untrace → Uninstall. That removes the app from PATH; run Uninstall in the GUI (or `untrace --uninstall`) first if you also want Chrome patches removed.

**Option B — from source (Admin)**

```powershell
python -m untrace --install --stealth-extension --launch-wrapper --chromedriver-cdc
python -m untrace --status
python -m untrace --uninstall
python -m untrace --gui
```

> **Smart App Control / WDAC:** may block the unsigned Chrome wrapper or patched chromedriver (`WinError 4551`). Turn SAC off if install succeeds but Chrome/Selenium still fail to launch. Install/uninstall kills Chrome processes on the machine.

## Feature flags

Each flag only enables its own layer. Combine as needed:

| Command | Stealth extension | Random profiles / launch wrapper | Chromedriver CDC patch |
|---------|-------------------|----------------------------------|------------------------|
| `--install` | ✓ | ✓ | ✓ |
| `--install --stealth-extension` | ✓ | ✗ | ✗ |
| `--install --launch-wrapper` | ✗ | ✓ | ✗ |
| `--install --chromedriver-cdc` | ✗ | ✗ | ✓ |
| `--install --stealth-extension --launch-wrapper --chromedriver-cdc` | ✓ | ✓ | ✓ |

Passing a flag off on reinstall disables that layer (e.g. `--install --stealth-extension` unpatches chromedrivers and removes the Chrome launch wrapper if it was there).

`--install` (root on Linux, Admin on Windows) writes the system Chrome launch wrapper and extension root (`/etc/untrace` or `%PROGRAMDATA%\Untrace`). On Linux it also writes `~/.local/share/untrace/chrome` for selenium-manager. Commands under `sudo` resolve the real user's home via `SUDO_USER` — not `/root`.

## Selenium

Bare driver only — no stealth flags, env vars, or capabilities in test code:

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

driver = webdriver.Chrome(options=Options())
```

When the wrapper is active it strips chromedriver junk (`--disable-blink-features=AutomationControlled`, `--test-type=webdriver`, …) and applies launcher flags. On Linux it also strips `--enable-automation` and `--headless`. On Windows `--enable-automation` stays so Chrome stays alive under remote debugging, and `driver.quit()` tears down `chrome_real` via a Job Object.

## Windows differences

| Topic | Behavior |
|-------|----------|
| **Stealth extension** | Web Store force-install only (`ExtensionInstallForcelist`). Non-enterprise Chrome blocks local/`http://` hosts. Install warms `%PROGRAMDATA%\Untrace\chrome_profile_template` once (Chrome writes `Secure Preferences` `location: 7`), then the launch wrapper copies that tree into each session profile. Do not use localhost update XML, `file://` CRX, or `--load-extension`. |
| **Random profiles** | Manual and Selenium both use `%TEMP%\chrome_random_profiles\profile_*`. Chromedriver’s `scoped_dir` is a junction into that tree. |
| **Chrome launch wrapper** | `chrome.exe` → C# wrapper; real browser → `chrome_real.exe`. Strips chromedriver junk (never `--enable-automation`), applies launcher flags, `WaitForExit`, Job Object `KILL_ON_JOB_CLOSE`. |
| **`--enable-automation`** | Kept in wrapper and chromedriver patch — Chrome exits under `--remote-debugging-port` without it. The automation infobar is expected and cosmetic; bot checks care about page-side signals, not that UI strip. |
| **Chromedriver CDC patch** | CDC + blank `test-type=webdriver` only. Selenium-manager redirect is Linux-only. |
| **Roots** | `%LOCALAPPDATA%\Untrace`, `%PROGRAMDATA%\Untrace` |

`--deploy` is not supported on Windows yet. If Selenium dies with “Chrome instance exited”, confirm the wrapper is current and `--enable-automation` still reaches Chrome. If the driver won’t start, check SAC/WDAC and restore via `--uninstall`.

## Tests

```bash
pytest tests/test_chromedriver.py
```

Requires a prior `python -m untrace --install --stealth-extension --launch-wrapper --chromedriver-cdc` (sudo/Admin as needed). `chrome_driver` in `tests/conftest.py` is intentionally minimal — fix failures in untrace, not the fixture. Linux-only unit tests are skipped on Windows.

| Test | Target |
|------|--------|
| `test_bot_sannysoft` | [bot.sannysoft.com](https://bot.sannysoft.com/) — Intoli + FPScanner tables all green |
| `test_bot_rebrowser` | [rebrowser-bot-detector](https://bot-detector.rebrowser.net/) — every check green; `mainWorldExecution`, `exposeFunctionLeak`, and `useragent` may stay neutral |
| `test_bot_akamai` | [hilton.com](https://www.hilton.com/en/) — Akamai BMP behavioral challenge |
| `test_bot_fpscanner` | [fpscanner.com/demo](https://fpscanner.com/demo/) |
| `test_untrace_extension` | `chrome://extensions/` |

## Custom scripts

Edit `custom.js` in the active untrace root, then re-run `--install`:

- Linux: `/etc/untrace/custom.js`
- Windows: `%ProgramData%\Untrace\custom.js`

Default stealth scripts live in `untrace/js/`. Enable or disable via `DEFAULT_CHROME_SCRIPTS` / `OPTIONAL_CHROME_SCRIPTS` in `untrace/__main__.py`.

| Script | What it does |
|--------|--------------|
| `utils.js` | Shared stealth helpers (`replaceGetter`, chained `toString` redirects) — runs first |
| `navigator.userAgent.js` | Strips `HeadlessChrome`, aligns UA/Client Hints (`uaFullVersion`, `platformVersion`, …) |
| `navigator.headless.js` | Forces `navigator.headless` to false |
| `cdp.js` | Mitigates CDP `Runtime.Enable` leak via stealthed `console.*` proxies (never reads `Error.stack`) |
| `akamai.js` | Scrubs CDC/window automation artifacts |
| `sourceurl.js` | Sanitizes `Error.stack` chromedriver evaluation markers |
| `navigator.webdriver.js` | Native-looking getter returning `false` |
| `iframe.webdriver.js` | Keeps `navigator.webdriver` false in iframes (no `contentWindow` Proxy) |
| `navigator.languages.js` | Sets `navigator.languages` |
| `navigator.vendor.js` | Sets `navigator.vendor` |
| `webgl.vendor.js` | Spoofs WebGL vendor/renderer |
| `window.outerdimensions.js` | Realistic `outerWidth` / `outerHeight` |
| `cleanup.js` | Removes the `utils` global after injection |
| `custom.js` | Your hooks (runs last) |

Optional (off by default): `iframe.contentWindow`, `navigator.plugins`, `navigator.permissions`, `media.codecs`, `chrome.app`, `chrome.runtime`, `chrome.csi`, `chrome.loadTimes`, `hairline.fix`.

> `iframe.contentWindow.js` is optional because its `document.createElement` hook can trip Akamai BMP on protected sites. Enable only if you need the srcdoc iframe fix.

## Development

```bash
uv sync --group dev
uv run task lint          # format + fix with Ruff
uv run task lint-check    # verify only (CI)
uv run task gui
uv run task build         # Setup.exe / .deb + extension zip → dist/
uv run task build-gui     # installer artifact only
uv run task pack-extension
uv run task test          # unit tests (skips browser suite)
uv run task test-browser  # needs a prior full --install
```

| Platform | Artifact |
|----------|----------|
| Windows | `dist/Untrace-*-Setup.exe` + `Portable.exe` + `Windows.zip` |
| Linux | `dist/untrace_*_amd64.deb` |
| Both | `dist/untrace-injector-*.zip` |

Windows Setup builds need [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`ISCC.exe`). Install with `winget install JRSoftware.InnoSetup` or `choco install innosetup`. Linux `.deb` builds need `dpkg-deb`.

The `.deb` / Setup install put `untrace` on `PATH`, a desktop/Start Menu launcher, and bundled docs. The GUI elevates on launch (UAC / pkexec); primary action is **Install** or **Update**. Logs live with the user deploy root (`~/.local/share/untrace/untrace.log` on Linux, `%LOCALAPPDATA%\Untrace\untrace.log` on Windows) and are removed by `--uninstall`.

CI (`.github/workflows/ci.yml`) lints on Linux, runs unit tests on Linux and Windows, then builds and uploads `dist/` artifacts.
