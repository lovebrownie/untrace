# Untrace

Untrace allows you to turn your automation undetectable, by simply running in the terminal. No need extra configuration.

## JavaScript injection

On install, untrace deploys a Chrome extension that runs stealth evasions at `document_start` on every page — including in every fresh Chrome instance. The evasions hide common automation fingerprints (webdriver flag, plugins, WebGL, chrome runtime, and more).

```bash
sudo python3 -m untrace --install
```

Stealth scripts and Chrome flags are defined in `untrace/__main__.py`. To add your own hooks, edit `/etc/untrace/custom.js` (Linux) or `%ProgramData%\Untrace\custom.js` (Windows), then re-run `--install`.

### Stealth evasions (from `js/`)

| Script | What it does |
|--------|--------------|
| `utils.js` | Shared proxy utilities (must run first) |
| `navigator.webdriver.js` | Removes `navigator.webdriver` |
| `navigator.plugins.js` | Fakes Chrome PDF / Native Client plugins |
| `navigator.languages.js` | Sets `navigator.languages` |
| `navigator.vendor.js` | Sets `navigator.vendor` |
| `navigator.permissions.js` | Fixes permissions query for notifications |
| `webgl.vendor.js` | Spoofs WebGL vendor/renderer strings |
| `media.codecs.js` | Fixes `canPlayType` codec responses |
| `chrome.app.js` | Mocks `window.chrome.app` |
| `chrome.runtime.js` | Mocks `window.chrome.runtime` |
| `chrome.csi.js` | Mocks `window.chrome.csi` |
| `chrome.loadTimes.js` | Mocks `window.chrome.loadTimes` |
| `iframe.contentWindow.js` | Fixes iframe `contentWindow` detection |
| `window.outerdimensions.js` | Sets `outerWidth` / `outerHeight` |
| `custom.js` | Your optional additions (deployed last) |

## To do
- [x] Isolate user data dir for each chrome instance
- [x] Insert javascript code into the browser for each page request