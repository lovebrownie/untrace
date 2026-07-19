# Untrace

<p align="center">
  <img src="assets/icon.svg" alt="untrace" width="128" height="128">
</p>

Untrace makes Chrome automation harder to detect. Install once, then use normal Chrome or bare Selenium — no per-script options, no test-side hacks.

Four optional layers, toggled independently:

| Layer | Flag | What it does |
|-------|------|-------------|
| **Stealth** | `--stealth` | MV3 extension — injects scripts at `document_start` in the `MAIN` world on every frame. **Linux:** local pack/seed. **Windows:** [Chrome Web Store force-install](https://chromewebstore.google.com/detail/untrace-injector/mgnlenokophofdnmlabkgpmlnolgomgj) |
| **Chrome wrapper** | `--flags` | Replaces Chrome with a wrapper in front of `chrome_real` (bash on Linux, C# on Windows). Strips chromedriver junk flags, applies launcher flags, seeds the extension into profiles (**Linux**). **Windows:** random profiles under `%TEMP%\chrome_random_profiles` for manual and Selenium |
| **Chromedriver patch** | `--chromedriver` | Neutralizes the CDC (`window.cdc_*`) injection in cached chromedriver binaries (and blanks `test-type=webdriver`). **Linux** also blanks `enable-automation` in the driver. **Windows** leaves `enable-automation` intact (Chrome needs it under remote debugging). Patched PE is unsigned — WDAC/SAC may block it (`WinError 4551`) |
| **Selenium-manager patch** | `--chromedriver` (with install) | Points Selenium's `selenium-manager` at the user Chrome wrapper so `webdriver.Chrome()` uses untrace automatically (**Linux only**) |

Bare `--install` (no flags) enables all three feature flags (`--stealth`, `--flags`, `--chromedriver`). On Windows, selenium-manager patching is skipped; stealth uses the Web Store extension (not the Linux local pack).

## Quick start

### Linux

**Install** (needs root). Re-run the same command to update:

```bash
sudo python3 -m untrace --install --stealth --flags --chromedriver
```

**Status** (shows what is actually active):

```bash
python3 -m untrace --status
```

```
Patched
Active untrace root: /etc/untrace
OK Stealth
OK Flags
OK Chrome wrapper
OK Chromedriver patch
OK Selenium-manager patch
```

**Uninstall** — removes everything: restores system Chrome, deletes `/etc/untrace` and `~/.local/share/untrace` (via `SUDO_USER`), unpatches chromedrivers:

```bash
sudo python3 -m untrace --uninstall
```

### Windows

CLI (Admin) or GUI. Install/uninstall closes Chrome automatically:

```powershell
python -m untrace --install --stealth --flags --chromedriver
python -m untrace --status
python -m untrace --uninstall

python -m untrace --gui
# or: poetry run task gui
```

Pack a Chrome Web Store upload zip (no `key` in manifest). The zip includes transparent icons (`icons/icon-16.png`, `48`, `128`) and sets `manifest.icons` + `action.default_icon`:

```powershell
python -m untrace --pack-extension
# optional: --output path\to\untrace-injector.zip --version 1.2.3
```

Default output: `%USERPROFILE%\Documents\Untrace\untrace-injector.zip`.

The GUI asks for Admin on launch (window icon from `assets/icon.ico`). Primary action is **Install** when nothing is present, **Update** when Untrace is already installed. Logs append to `%USERPROFILE%\Documents\Untrace\untrace.log`.

Build a standalone `dist\Untrace.exe` (optional):

```powershell
poetry run task build-gui
```

`--deploy` is not supported on Windows yet. `--stealth` force-installs [Untrace Injector](https://chromewebstore.google.com/detail/untrace-injector/mgnlenokophofdnmlabkgpmlnolgomgj) from the Chrome Web Store (Admin for policy keys) and warms `%PROGRAMDATA%\Untrace\chrome_profile_template`. `--chromedriver` patches cached drivers (keep App Control off if the unsigned PE is blocked).

## Windows

Windows uses the **flags / Chrome wrapper** plus optional **Web Store stealth**. Differences from Linux:

| Topic | Behavior |
|-------|----------|
| **Stealth** | `ExtensionInstallForcelist` with the Chrome Web Store update URL only (non-enterprise Chrome blocks local/`http://` hosts — `[BLOCKED]` in `chrome://policy`). Install warms `%PROGRAMDATA%\Untrace\chrome_profile_template` once so force-install can write `Secure Preferences` (`location: 7`). That warmup starts Chrome **minimized / off-screen**, then **kills all `chrome_real.exe` / `chrome.exe` processes**. The wrapper **copies** the template into each session profile before launch (no DevTools delay for Selenium). |
| **GUI** | `python -m untrace --gui` (or `poetry run task gui`). Elevates via UAC. Shows **Install** or **Update**, status cards, in-app confirmations. Writes `%USERPROFILE%\Documents\Untrace\untrace.log`. Optional `poetry run task build-gui` → `dist\Untrace.exe`. |
| **Profiles** | Manual (`--flags`) and Selenium both use `%TEMP%\chrome_random_profiles\profile_*`. Chromedriver’s temp `scoped_dir` is a **junction** into that tree so `DevToolsActivePort` still resolves. |
| **Chrome wrapper** | `chrome.exe` → C# wrapper; real browser → `chrome_real.exe`. Strips chromedriver junk, applies launcher flags, **waits** for Chrome (no `exec`). Tracks `chrome_real` in a Job Object (`KILL_ON_JOB_CLOSE`) so `driver.quit()` also tears down Chrome children. |
| **`--enable-automation`** | **Kept** in the wrapper **and** in the chromedriver binary patch — Chrome exits under `--remote-debugging-port` without it |
| **Chromedriver patch** | CDC + blank `test-type=webdriver`; does **not** blank `enable-automation`. Edited PE is unsigned — SAC/WDAC may block (`WinError 4551`) |
| **Selenium-manager** | Not patched (bash wrapper is Linux-only) |
| **Roots** | `%LOCALAPPDATA%\Untrace`, `%PROGRAMDATA%\Untrace` |

If Selenium dies with “Chrome instance exited” after install, confirm the C# wrapper is current and that `--enable-automation` still reaches Chrome (Windows must not strip or binary-blank that flag). If the driver won’t start at all, check Smart App Control / WDAC (`WinError 4551`) and restore from `.untrace.bak` via `--uninstall` if needed.

> **Warning:** If **Smart App Control** (or another Application Control / WDAC policy) is enabled on Windows, untrace may not work. The Chrome wrapper replaces `chrome.exe` with an unsigned C# binary, and `--chromedriver` produces an unsigned `chromedriver.exe`; Smart App Control can block either (`WinError 4551` for the driver). Turn Smart App Control off (or switch it to evaluation/off) if install succeeds but Chrome or Selenium still fails to launch. Install/uninstall (CLI or GUI) kills Chrome processes on the machine, including during stealth template warmup.

## Feature flags

Each flag only enables its own layer. Combine as needed:

| Command | Stealth | Flags | Chrome wrapper | Chromedriver |
|---------|---------|-------|----------------|--------------|
| `--install` | ✓ | ✓ | ✓ | ✓ |
| `--install --stealth` | ✓ | ✗ | ✗ | ✗ |
| `--install --flags` | ✗ | ✓ | ✓ | ✗ |
| `--install --chromedriver` | ✗ | ✗ | ✗ | ✓ |
| `--install --stealth --chromedriver` | ✓ | ✗ | ✗ | ✓ |
| `--install --stealth --flags --chromedriver` | ✓ | ✓ | ✓ | ✓ |

- **`--stealth`** — extension only. Stock Chrome binary, normal profile, no chromedriver patch.
- **`--flags`** — patches Chrome (`chrome` → wrapper, real binary → `chrome_real`). Random `--user-data-dir` on manual launches (Linux) / `%TEMP%\chrome_random_profiles` for manual **and** Selenium (Windows). No extension unless `--stealth` is also passed.
- **`--chromedriver`** — patches/unpatches Selenium's cached chromedriver binaries (and selenium-manager wrappers on Linux).

Passing a flag off on reinstall disables that layer (e.g. `--install --stealth` unpatches chromedrivers and removes the Chrome wrapper if it was there).

## Install

`--install` (root on Linux, Admin on Windows) writes the system Chrome wrapper, extension root (`/etc/untrace` or `%PROGRAMDATA%\Untrace`), and on Linux also `~/.local/share/untrace/chrome` for Selenium-manager. Commands run under `sudo` resolve the real user's home via `SUDO_USER` — not `/root`.

## Selenium

Bare driver only — no stealth flags, env vars, or capabilities in test code:

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

driver = webdriver.Chrome(options=Options())
```

When the wrapper is active it strips chromedriver junk (`--disable-blink-features=AutomationControlled`, `--test-type=webdriver`, …) and applies launcher flags before launch. On **Linux** it also strips `--enable-automation` and `--headless` (headless is re-handled via the Linux wrapper). On **Windows** `--enable-automation` is left in place so Chrome stays alive, and `driver.quit()` tears down `chrome_real` via a Job Object (otherwise Windows can leave orphan browser processes between tests).

## Tests

```bash
pytest tests/test_chromedriver.py
```

Requires a prior `python -m untrace --install --stealth --flags --chromedriver` (sudo/Admin as needed). `chrome_driver` in `tests/conftest.py` is intentionally minimal — fix failures in untrace, not the fixture. Linux-only unit tests are skipped on Windows.

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

### Stealth scripts

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

## Project layout

```
assets/
  icon.svg               Brand mark (transparent background)
  icon.png / icon-*.png  Raster icons (16 / 48 / 128) for the extension + GUI
  icon.ico               Windows GUI / PyInstaller icon
untrace/
  __main__.py            CLI, Chrome wrapper, script catalog
  injector.py            Extension build, icons → manifest, profile seeding
  chromedriver_patch.py  CDC patch / unpatch with .untrace.bak
  selenium_manager_patch.py  Patch selenium-manager to use the Chrome wrapper
  config.py              Persisted feature flags per root
  gui_windows.py         Windows install/update GUI
  applog.py              Documents\\Untrace\\untrace.log tee
  js/                    Stealth injection sources
tests/
  test_chromedriver.py   Browser integration tests
  conftest.py            Bare Selenium fixture
```

Linux `--install --stealth` and `--pack-extension` copy `assets/icon-{16,48,128}.png` into the extension `icons/` folder and wire them into `manifest.json` (`icons` + `action.default_icon`).

## Development

```bash
poetry install
poetry run task lint          # format + fix with Ruff
poetry run task lint-check    # verify only (CI)
poetry run task gui           # Windows GUI (Admin)
poetry run task build-gui     # dist\\Untrace.exe (Windows + PyInstaller)
python -m untrace --pack-extension   # Chrome Web Store zip → Documents/Untrace/
pytest
```