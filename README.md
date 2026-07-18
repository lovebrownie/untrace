# Untrace

Untrace makes Chrome automation harder to detect. Install once, then use normal Chrome or bare Selenium — no per-script options, no test-side hacks.

Four optional layers, toggled independently:

| Layer | Flag | What it does |
|-------|------|-------------|
| **Stealth** | `--stealth` | MV3 extension — injects scripts at `document_start` in the `MAIN` world on every frame. **Linux:** local pack/seed. **Windows:** [Chrome Web Store force-install](https://chromewebstore.google.com/detail/untrace-injector/mgnlenokophofdnmlabkgpmlnolgomgj) |
| **Chrome wrapper** | `--flags` | Replaces Chrome with a wrapper in front of `chrome_real` (bash on Linux, C# on Windows). Strips chromedriver junk flags, applies launcher flags, seeds the extension into profiles (**Linux**). **Windows:** random profiles under `%TEMP%\chrome_random_profiles` for manual and Selenium |
| **Chromedriver patch** | `--chromedriver` | Neutralizes the CDC (`window.cdc_*`) injection in cached chromedriver binaries (and blanks `test-type=webdriver`). **Linux** also blanks `enable-automation` in the driver. **Windows** leaves `enable-automation` intact (Chrome needs it under remote debugging). Patched PE is unsigned — WDAC/SAC may block it (`WinError 4551`) |
| **Selenium-manager patch** | `--chromedriver` (with deploy/install) | Points Selenium's `selenium-manager` at the user Chrome wrapper so `webdriver.Chrome()` uses untrace automatically (**Linux only**) |

Bare `--install` or `--deploy` (no flags) enables all three feature flags (`--stealth`, `--flags`, `--chromedriver`). On Windows, selenium-manager patching is skipped; stealth uses the Web Store extension (not the Linux local pack).

## Quick start

### Linux

**Full system install** (needs root):

```bash
sudo python3 -m untrace --install --stealth --flags --chromedriver
```

**Day-to-day updates** (no password):

```bash
python3 -m untrace --deploy --stealth --flags --chromedriver
```

**Status** (shows what is actually active):

```bash
python3 -m untrace --status
```

```
Patched
Active untrace root: /home/you/.local/share/untrace
✓ Stealth
✓ Flags
✓ Chrome wrapper
✓ Chromedriver patch
✓ Selenium-manager patch
```

**Uninstall** — removes everything: restores system Chrome, deletes `/etc/untrace` and `~/.local/share/untrace` (via `SUDO_USER`), unpatches chromedrivers:

```bash
sudo python3 -m untrace --uninstall
```

### Windows

Run an elevated PowerShell / terminal (Admin), close Chrome first:

```powershell
python -m untrace --install --stealth --flags --chromedriver
python -m untrace --status
python -m untrace --uninstall
```

`--deploy` is not supported on Windows yet. `--stealth` force-installs [Untrace Injector](https://chromewebstore.google.com/detail/untrace-injector/mgnlenokophofdnmlabkgpmlnolgomgj) from the Chrome Web Store (Admin for policy keys) and warms `%PROGRAMDATA%\Untrace\chrome_profile_template`. `--chromedriver` patches cached drivers (keep App Control off if the unsigned PE is blocked).

## Windows

Windows uses the **flags / Chrome wrapper** plus optional **Web Store stealth**. Differences from Linux:

| Topic | Behavior |
|-------|----------|
| **Stealth** | `ExtensionInstallForcelist` with the Chrome Web Store update URL only (non-enterprise Chrome blocks local/`http://` hosts — `[BLOCKED]` in `chrome://policy`). Install warms `%PROGRAMDATA%\Untrace\chrome_profile_template` once so force-install can write `Secure Preferences` (`location: 7`). That warmup opens a normal Chrome window briefly, then **kills all `chrome_real.exe` / `chrome.exe` processes**. The wrapper **copies** the template into each session profile before launch (no DevTools delay for Selenium). |
| **Profiles** | Manual (`--flags`) and Selenium both use `%TEMP%\chrome_random_profiles\profile_*`. Chromedriver’s temp `scoped_dir` is a **junction** into that tree so `DevToolsActivePort` still resolves. |
| **Chrome wrapper** | `chrome.exe` → C# wrapper; real browser → `chrome_real.exe`. Strips chromedriver junk, applies launcher flags, **waits** for Chrome (no `exec`). Tracks `chrome_real` in a Job Object (`KILL_ON_JOB_CLOSE`) so `driver.quit()` also tears down Chrome children. |
| **`--enable-automation`** | **Kept** in the wrapper **and** in the chromedriver binary patch — Chrome exits under `--remote-debugging-port` without it |
| **Chromedriver patch** | CDC + blank `test-type=webdriver`; does **not** blank `enable-automation`. Edited PE is unsigned — SAC/WDAC may block (`WinError 4551`) |
| **Selenium-manager** | Not patched (bash wrapper is Linux-only) |
| **Roots** | `%LOCALAPPDATA%\Untrace`, `%PROGRAMDATA%\Untrace` |

If Selenium dies with “Chrome instance exited” after install, confirm the C# wrapper is current and that `--enable-automation` still reaches Chrome (Windows must not strip or binary-blank that flag). If the driver won’t start at all, check Smart App Control / WDAC (`WinError 4551`) and restore from `.untrace.bak` via `--uninstall` if needed.

> **Warning:** If **Smart App Control** (or another Application Control / WDAC policy) is enabled on Windows, untrace may not work. The Chrome wrapper replaces `chrome.exe` with an unsigned C# binary, and `--chromedriver` produces an unsigned `chromedriver.exe`; Smart App Control can block either (`WinError 4551` for the driver). Turn Smart App Control off (or switch it to evaluation/off) if install succeeds but Chrome or Selenium still fails to launch. Close other Chrome windows before `--install --stealth`: template warmup ends by killing all Chrome processes on the machine.

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

## Install vs deploy

| | `--install` | `--deploy` |
|---|-------------|------------|
| Root required | Yes | No |
| System Chrome wrapper | `/opt/google/chrome/chrome` | — |
| User Chrome wrapper | updates `~/.local/share/untrace/chrome` if it exists | `~/.local/share/untrace/chrome` |
| Extension root | `/etc/untrace` | `~/.local/share/untrace` |
| When to use | Once per machine, or to change system Chrome | After editing scripts, routine iteration |

The system wrapper prefers `~/.local/share/untrace` when it exists (from `--deploy`), so deploy updates land without re-running sudo.

Commands run under `sudo` resolve the real user's home via `SUDO_USER` — not `/root`.

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

Requires a prior install: Linux `python -m untrace --deploy --stealth --flags --chromedriver` (or `--install`); Windows `python -m untrace --install --stealth --flags --chromedriver`. `chrome_driver` in `tests/conftest.py` is intentionally minimal — fix failures in untrace, not the fixture. Linux-only unit tests are skipped on Windows.

| Test | Target |
|------|--------|
| `test_bot_sannysoft` | [bot.sannysoft.com](https://bot.sannysoft.com/) — Intoli + FPScanner tables all green |
| `test_bot_rebrowser` | [rebrowser-bot-detector](https://bot-detector.rebrowser.net/) — every check green; `mainWorldExecution`, `exposeFunctionLeak`, and `useragent` may stay neutral |
| `test_bot_akamai` | [hilton.com](https://www.hilton.com/en/) — Akamai BMP behavioral challenge |
| `test_bot_fpscanner` | [fpscanner.com/demo](https://fpscanner.com/demo/) |
| `test_untrace_extension` | `chrome://extensions/` |

## Custom scripts

Edit `custom.js` in the active untrace root, then re-run install or deploy:

- Linux system: `/etc/untrace/custom.js`
- Linux user deploy: `~/.local/share/untrace/custom.js`
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
untrace/
  __main__.py            CLI, Chrome wrapper, script catalog
  injector.py            Extension build, profile seeding
  chromedriver_patch.py  CDC patch / unpatch with .untrace.bak
  selenium_manager_patch.py  Patch selenium-manager to use the Chrome wrapper
  config.py              Persisted feature flags per root
  js/                    Stealth injection sources
tests/
  test_chromedriver.py   Browser integration tests
  conftest.py            Bare Selenium fixture
```

## Development

```bash
poetry install
poetry run task lint          # format + fix with Ruff
poetry run task lint-check    # verify only (CI)
pytest
```