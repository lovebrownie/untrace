# Untrace

<p align="center">
  <img src="assets/icon.svg" alt="untrace" width="128" height="128">
</p>

Install once, then use normal Chrome or bare Selenium.

| Layer | Flag |
|-------|------|
| Stealth extension | `--stealth-extension` |
| Chrome launch wrapper / random profiles | `--launch-wrapper` |
| Chromedriver CDC patch | `--chromedriver-cdc` |

Bare `--install` enables all three.

## Install

### Linux

```bash
sudo python3 -m untrace --install
python3 -m untrace --status
sudo python3 -m untrace --uninstall
```

### Windows

```powershell
python -m untrace --install
python -m untrace --status
python -m untrace --uninstall
```

On Windows, Smart App Control / WDAC may block the unsigned wrapper (`WinError 4551`).

## Selenium

```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

driver = webdriver.Chrome(options=Options())
```

Works the same for Playwright (`channel="chrome"`), Puppeteer, and other tools that launch the system Chrome.

## Custom scripts

Edit `custom.js` in the active root, then re-run `--install`:

- Linux: `/etc/untrace/custom.js`
- Windows: `%ProgramData%\Untrace\custom.js`

Default scripts live in `untrace/js/`.

## Development

```bash
uv sync --group dev
uv run task lint
uv run task test
uv run task test-browser   # needs a prior --install
```
