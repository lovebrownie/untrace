# Untrace

<p>
  <img src="assets/icon.svg" alt="untrace" width="128" height="128">
</p>

Untrace is a system-level stealth stack for Chrome. Install it once, then use the browser normally. No custom flags, no extra extensions in your project, no profile scripts to maintain.

It ships as three modules you can toggle at install time. The **stealth extension** patches common bot-detection signals in the page. The **launch wrapper** gives every Chrome start a fresh random profile and anti-detection launch flags. The **chromedriver CDC patch** strips automation fingerprints from chromedriver binaries on disk.

You don't need to keep asking whether your setup is stealthy enough. Untrace wires it in at the OS level.

**Untrace GUI**

<p>
  <img src="assets/app-installed.png" alt="untrace status, all modules online" width="640">
</p>

**Fresh Chrome profile**

<p>
  <img src="assets/chrome-profile.png" alt="Chrome launched with a random profile" width="560">
</p>

## Modules

| Module | Flag |
|--------|------|
| Stealth extension | `--stealth-extension` |
| Random profiles / Chrome launch wrapper | `--launch-wrapper` |
| Chromedriver CDC patch | `--chromedriver-cdc` |

## Install

Download the [latest release](https://github.com/lovebrownie/untrace/releases/latest), run the installer, and use the GUI to enable modules. You can also install from the terminal.

### Terminal

**Linux**

```bash
curl -fsSL "https://raw.githubusercontent.com/lovebrownie/untrace/main/scripts/install.sh" | bash
```

**Windows**

```powershell
irm "https://raw.githubusercontent.com/lovebrownie/untrace/main/scripts/install.ps1" | iex
```

## How to use

Enable all modules:

```bash
untrace --install --stealth-extension --launch-wrapper --chromedriver-cdc
```

Check status:

```bash
untrace --status
```

Uninstall modules:

```bash
untrace --uninstall
```
