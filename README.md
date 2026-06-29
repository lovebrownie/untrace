# Untrace

Untrace makes Chrome automation harder to detect. Install once, then use normal Chrome or bare Selenium — no per-script options, no test-side hacks.

It works in three layers:

1. **Chrome wrapper** — replaces the system `chrome` binary. Strips chromedriver automation flags, applies launcher flags, seeds the extension into each profile, and runs headed (even when chromedriver passes `--headless`) via `xvfb-run` when available.
2. **MV3 extension** — injects stealth scripts at `document_start` in the `MAIN` world on every frame, including fresh profiles and Selenium sessions.
3. **Chromedriver patch** — neutralizes the CDC (`window.cdc_*`) injection string in cached chromedriver binaries.

## Quick start

**One-time system install** (needs root — wires `/opt/google/chrome/chrome`):

```bash
sudo python3 -m untrace --install --stealth --flags
```

**Day-to-day updates** (no password — extension, user wrapper, chromedriver patch):

```bash
python3 -m untrace --deploy --stealth --flags
```

Check status:

```bash
python3 -m untrace --status
```

Uninstall:

```bash
sudo python3 -m untrace --uninstall
```

## Install vs deploy

| | `--install` | `--deploy` |
|---|-------------|------------|
| Root required | Yes | No |
| Chrome wrapper | `/opt/google/chrome/chrome` | `~/.local/share/untrace/chrome` |
| Extension root | `/etc/untrace` | `~/.local/share/untrace` |
| When to use | Once, on a new machine | After changing scripts or iterating on tests |

After `--install`, the system wrapper prefers `~/.local/share/untrace` when it exists (from `--deploy`), so deploy updates land without re-running sudo.

## Selenium

Use bare `webdriver.Chrome(options=Options())`. Do not add stealth flags, env vars, or capabilities in test code — untrace handles that globally.

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

driver = webdriver.Chrome(options=Options())
```

The wrapped Chrome binary strips `--enable-automation`, `--disable-blink-features=AutomationControlled`, and other chromedriver junk before launch.

## Tests

```bash
pytest tests/test_chromedriver.py
```

Browser integration tests auto-run `--deploy` before the module. `chrome_driver` in `tests/conftest.py` stays minimal — fix failures in the wrapper, extension, or chromedriver patch, not in the fixture.

## Custom scripts

Edit `custom.js` in the active untrace root, then re-run install or deploy:

- Linux system: `/etc/untrace/custom.js`
- Linux user deploy: `~/.local/share/untrace/custom.js`
- Windows: `%ProgramData%\Untrace\custom.js`

Default stealth scripts live in `untrace/js/`. Enable or disable scripts via `DEFAULT_CHROME_SCRIPTS` / `OPTIONAL_CHROME_SCRIPTS` in `untrace/__main__.py`.

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

Optional scripts (off by default): `navigator.plugins`, `navigator.permissions`, `media.codecs`, `chrome.app`, `chrome.runtime`, `chrome.csi`, `chrome.loadTimes`, `hairline.fix`.

## Project layout

```
untrace/
  __main__.py          CLI, Chrome wrapper script, script catalog
  injector.py          Extension build, profile seeding, CRX packing
  chromedriver_patch.py  CDC string neutralization
  config.py            Persisted install feature flags
  js/                  Stealth injection sources
tests/
  test_chromedriver.py Browser integration tests (bot.sannysoft, Akamai, FPScanner)
  conftest.py          Bare Selenium fixture
```

## Development

```bash
poetry install
poetry run task lint
pytest
```