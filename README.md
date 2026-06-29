# Untrace

Untrace makes Chrome automation harder to detect. Install once, then use normal Chrome or bare Selenium — no per-script options, no test-side hacks.

Three optional layers, toggled independently:

| Layer | Flag | What it does |
|-------|------|-------------|
| **Stealth** | `--stealth` | MV3 extension — injects scripts at `document_start` in the `MAIN` world on every frame |
| **Chrome wrapper** | `--flags` | Replaces the `chrome` binary with a bash script in front of `chrome_real`. Strips chromedriver junk flags, applies launcher flags, seeds the extension into profiles. Manual launches get a **random profile** only when `--flags` is on |
| **Chromedriver patch** | `--chromedriver` | Neutralizes the CDC (`window.cdc_*`) injection in cached chromedriver binaries (restored from `.untrace.bak` on uninstall) |

Bare `--install` or `--deploy` (no flags) enables all three.

## Quick start

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
```

**Uninstall** — removes everything: restores system Chrome, deletes `/etc/untrace` and `~/.local/share/untrace` (via `SUDO_USER`), unpatches chromedrivers:

```bash
sudo python3 -m untrace --uninstall
```

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
- **`--flags`** — patches Chrome (`chrome` → wrapper script, real binary → `chrome_real`). Random `--user-data-dir` on manual launches. No extension unless `--stealth` is also passed.
- **`--chromedriver`** — patches/unpatches Selenium's cached chromedriver binaries only.

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

When the wrapper is active it strips `--enable-automation`, `--disable-blink-features=AutomationControlled`, `--headless`, and other chromedriver junk before launch.

## Tests

```bash
pytest tests/test_chromedriver.py
```

Auto-runs `--deploy --stealth --flags --chromedriver` before the module. `chrome_driver` in `tests/conftest.py` is intentionally minimal — fix failures in untrace, not the fixture.

## Custom scripts

Edit `custom.js` in the active untrace root, then re-run install or deploy:

- Linux system: `/etc/untrace/custom.js`
- Linux user deploy: `~/.local/share/untrace/custom.js`
- Windows: `%ProgramData%\Untrace\custom.js`

Default stealth scripts live in `untrace/js/`. Enable or disable via `DEFAULT_CHROME_SCRIPTS` / `OPTIONAL_CHROME_SCRIPTS` in `untrace/__main__.py`.

### Stealth scripts

| Script | What it does |
|--------|--------------|
| `utils.js` | Shared proxy helpers (runs first) |
| `navigator.userAgent.js` | Strips `HeadlessChrome` from UA |
| `navigator.headless.js` | Forces `navigator.headless` to false |
| `cdp.js` | Hides CDP-related leaks |
| `akamai.js` | Scrubs CDC/window automation artifacts |
| `sourceurl.js` | Fixes `//# sourceURL` detection |
| `navigator.webdriver.js` | Sets `navigator.webdriver` to false |
| `iframe.contentWindow.js` | Fixes iframe `contentWindow` probes |
| `iframe.webdriver.js` | Patches webdriver inside iframes |
| `navigator.languages.js` | Sets `navigator.languages` |
| `navigator.vendor.js` | Sets `navigator.vendor` |
| `webgl.vendor.js` | Spoofs WebGL vendor/renderer |
| `window.outerdimensions.js` | Realistic `outerWidth` / `outerHeight` |
| `cleanup.js` | Removes transient automation markers |
| `custom.js` | Your hooks (runs last) |

Optional (off by default): `navigator.plugins`, `navigator.permissions`, `media.codecs`, `chrome.app`, `chrome.runtime`, `chrome.csi`, `chrome.loadTimes`, `hairline.fix`.

## Project layout

```
untrace/
  __main__.py            CLI, Chrome wrapper, script catalog
  injector.py            Extension build, profile seeding
  chromedriver_patch.py  CDC patch / unpatch with .untrace.bak
  config.py              Persisted feature flags per root
  js/                    Stealth injection sources
tests/
  test_chromedriver.py   Browser integration tests
  conftest.py            Bare Selenium fixture
```

## Development

```bash
poetry install
poetry run task lint
pytest
```