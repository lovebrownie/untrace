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

**Option A — `.deb` (GUI + `untrace` on `PATH`)**

```bash
poetry run task build-gui   # or: python -m untrace --build
sudo apt install ./dist/untrace_0.1.0_amd64.deb

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
sudo python3 -m untrace --install --stealth --flags --chromedriver
python3 -m untrace --status
sudo python3 -m untrace --uninstall
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

`--uninstall` restores system Chrome, deletes `/etc/untrace` and `~/.local/share/untrace` (via `SUDO_USER`), and unpatches chromedrivers / selenium-manager.

### Windows

**Option A — Setup installer (GUI + `untrace` on PATH)**

```powershell
poetry run task build-gui
# dist\Untrace-v0.1.0.exe          portable (Admin UAC)
# dist\Untrace-v0.1.0-Setup.exe    installer (needs Inno Setup to build)
# run the Setup, or the portable exe
untrace              # after Setup: on PATH
untrace --status
untrace --gui
```

Uninstall from Windows Settings → Apps, or Start Menu → Untrace → Uninstall. That removes the app from PATH; run Uninstall in the GUI (or `untrace --uninstall`) first if you also want Chrome patches removed.

**Option B — from source (Admin)**

```powershell
python -m untrace --install --stealth --flags --chromedriver
python -m untrace --status
python -m untrace --uninstall

python -m untrace --gui
# or: poetry run task gui
```

## Build artifacts

```bash
python -m untrace --build
# or: poetry run task build
```

| Platform | Artifact |
|----------|----------|
| Windows | `dist/Untrace-v0.1.0-Setup.exe` (Inno Setup) + `dist/Untrace-v0.1.0.exe` (portable) |
| Linux | `dist/untrace_0.1.0_amd64.deb` |
| Both | `dist/untrace-injector-v0.1.0.zip` (extension; version from `pyproject.toml`) |

`poetry run task build` always packs the extension zip after the GUI/installer step (even if the Windows Setup pack fails, the portable `.exe` and zip are still written when possible).

GUI-only: `poetry run task build-gui`. Extension only: `poetry run task pack-extension`.

The Linux `.deb` / Windows Setup install:

- `untrace` on `PATH` (CLI + GUI)
- Desktop / Start Menu launcher + icon
- License / docs bundled with the install

The GUI asks for elevated privileges on launch (UAC on Windows, pkexec/sudo on Linux). On Windows the console host is detached so only the app window appears (CLI still uses a normal console). Window title is `untrace vX.Y.Z`. Primary action is **Install** when nothing is present, **Update** when Untrace is already installed. Logs append to `Documents/Untrace/untrace.log`.

Pack a Chrome Web Store upload zip (no `key` in manifest):

```bash
python -m untrace --pack-extension
```

`--deploy` is not supported on Windows yet. `--stealth` force-installs [Untrace Injector](https://chromewebstore.google.com/detail/untrace-injector/mgnlenokophofdnmlabkgpmlnolgomgj) from the Chrome Web Store (Admin for policy keys) and warms `%PROGRAMDATA%\Untrace\chrome_profile_template`. `--chromedriver` patches cached drivers (keep App Control off if the unsigned PE is blocked).

## Windows notes

Windows uses the **flags / Chrome wrapper** plus optional **Web Store stealth**. Differences from Linux:

| Topic | Behavior |
|-------|----------|
| **Stealth** | `ExtensionInstallForcelist` with the Chrome Web Store update URL only (non-enterprise Chrome blocks local/`http://` hosts — `[BLOCKED]` in `chrome://policy`). Install warms `%PROGRAMDATA%\Untrace\chrome_profile_template` once so force-install can write `Secure Preferences` (`location: 7`). That warmup starts Chrome **minimized / off-screen**, then **kills all `chrome_real.exe` / `chrome.exe` processes**. The wrapper **copies** the template into each session profile before launch (no DevTools delay for Selenium). |
| **GUI** | `python -m untrace --gui` (or `poetry run task gui`). Elevates via UAC; hides the PyInstaller console so only the Tk window shows. Shows **Install** or **Update**, status cards, in-app confirmations. Writes `Documents/Untrace/untrace.log`. |
| **Build** | `python -m untrace --build` → `dist/Untrace-vX.Y.Z-Setup.exe` + `dist/Untrace-vX.Y.Z.exe` (portable) + extension zip. Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`ISCC.exe`) — `winget install JRSoftware.InnoSetup` or `choco install innosetup`. |
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
scripts/
  build.py               Dist packer (PyInstaller + .deb / Inno Setup)
  windows/untrace.iss    Windows installer script
assets/
  icon.svg               Brand mark (transparent background)
  icon.png / icon-*.png  Raster icons (16 / 48 / 128) for the extension + GUI
  icon.ico               GUI / installer icon
untrace/
  __init__.py            Exports __version__ (from pyproject.toml)
  version.py             Reads [project].version; artifact name helpers
  __main__.py            CLI, Chrome wrapper, script catalog
  injector.py            Extension build, icons → manifest, profile seeding
  chromedriver.py        CDC patch / unpatch with .untrace.bak
  selenium.py            Patch selenium-manager to use the Chrome wrapper
  config.py              Persisted feature flags per root
  gui.py                 Install/update GUI (Windows + Linux)
  applog.py              Documents/Untrace/untrace.log tee
  js/                    Stealth injection sources
tests/
  test_chromedriver.py   Browser integration tests
  test_chromedriver_unit.py  Chromedriver CDC patch unit tests
  test_selenium.py       Selenium-manager patch unit tests
  conftest.py            Bare Selenium fixture
```

Linux `--install --stealth` and `--pack-extension` copy `assets/icon-{16,48,128}.png` into the extension `icons/` folder and wire them into `manifest.json` (`icons` + `action.default_icon`).

One version for the package, extension, and GUI — bump `[project].version` in `pyproject.toml`:

```python
from untrace import __version__
```

Extension builds and `--pack-extension` use `__version__` unless `--version` is passed.

## Development

```bash
poetry install
poetry run task lint          # format + fix with Ruff
poetry run task lint-check    # verify only (CI)
poetry run task gui           # install/uninstall GUI (elevates)
poetry run task build         # Setup.exe / .deb + extension zip → dist/
poetry run task build-gui     # installer artifact only
poetry run task pack-extension  # extension zip only
python -m untrace --build     # same as task build
pytest
```

Windows installer builds need [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`ISCC.exe` on `PATH`, or the default install location). Install with `winget install JRSoftware.InnoSetup` or `choco install innosetup`. Linux `.deb` builds need `dpkg-deb`.

CI (`.github/workflows/ci.yml`) runs lint + unit tests on Ubuntu and Windows (`fail-fast`: one failure cancels the other test job). Build only starts after every test job succeeds, then uploads `dist/` artifacts named `untrace-<OS>-vX.Y.Z`.
