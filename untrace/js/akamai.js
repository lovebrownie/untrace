// Optional — NOT in DEFAULT_CHROME_SCRIPTS. Enable only when you need Selenium leak
// cleanup on non-Akamai pages. Keeps a minimal surface: CDC keys only, no API proxies.

() => {
  const LEAK_RE =
    /^(?:\$cdc_|cdc_|__webdriver|__driver|__selenium|_selenium|_Selenium|calledSelenium|webdriver_|selenium_|domAutomation|domAutomationController)/i

  const scrubObject = (obj) => {
    if (!obj) return
    for (const key of Object.getOwnPropertyNames(obj)) {
      if (LEAK_RE.test(key)) {
        try {
          delete obj[key]
        } catch (_) {}
      }
    }
  }

  scrubObject(window)
  scrubObject(document)
}