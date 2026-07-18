from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

PAGE_TIMEOUT = 30

BLOCKED_MARKERS = (
    "access denied",
    "request denied",
    "errors.edgesuite.net",
    "you don't have permission to access",
    "something went wrong",
)

REBROWSER_TEST_URL = "https://bot-detector.rebrowser.net/"
SANNY_SOFT_URL = "https://bot.sannysoft.com/"
SANNY_SOFT_FPSCANNER_LAST = "VIDEO_CODECS"

# rating 0 is OK for checks Selenium cannot trigger without failing another probe.
REBROWSER_OPTIONAL_NEUTRAL = frozenset(
    {"mainWorldExecution", "exposeFunctionLeak", "useragent"}
)


def _wait(driver) -> WebDriverWait:
    return WebDriverWait(driver, PAGE_TIMEOUT)


def _body_text(driver) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text.strip()
    except Exception:
        return ""


def _page_content(driver) -> tuple[str, str]:
    return (driver.title or "").strip(), _body_text(driver)


def _page_passes_checks(driver, *, title_contains: str | None = None) -> bool:
    title, body = _page_content(driver)
    if not title or not body or len(body) <= 30:
        return False
    if title_contains and title_contains.lower() not in title.lower():
        return False
    combined = f"{title}\n{body}".lower()
    return not any(marker in combined for marker in BLOCKED_MARKERS)


def _wait_for_page_ready(driver, *, title_contains: str | None = None) -> None:
    _wait(driver).until(lambda d: _page_passes_checks(d, title_contains=title_contains))


def _fpscanner_failures(body: str) -> list[str]:
    if "bot detection" not in body.lower():
        return ["Bot Detection section missing from page body"]

    section = body.lower().split("bot detection", 1)[1]
    if "bot detected" in section:
        return ["FPScanner reported: Bot Detected"]

    lines = body.split("Bot Detection", 1)[1].splitlines()
    failures: list[str] = []
    for idx, line in enumerate(lines):
        if line.strip() != "DETECTED":
            continue
        label = ""
        for back in range(idx - 1, max(idx - 4, -1), -1):
            candidate = lines[back].strip()
            if candidate and candidate not in {"✕", "▼", "OK", "✓"}:
                label = candidate
                break
        failures.append(label or "unknown check")
    return failures


def _assert_page_loaded(driver, *, title_contains: str | None = None) -> None:
    title, body = _page_content(driver)
    combined = f"{title}\n{body}".lower()

    assert title, f"Title should not be empty (body: {body[:300]!r})"
    assert body, f"Page body should not be empty (title: {title!r})"

    for marker in BLOCKED_MARKERS:
        assert marker not in combined, (
            f"Page blocked — found {marker!r} (title: {title!r}, body: {body[:400]!r})"
        )

    if title_contains is not None:
        assert title_contains.lower() in title.lower(), (
            f"Expected {title_contains!r} in title, got {title!r} "
            f"(body: {body[:300]!r})"
        )


def _assert_fpscanner_clean(driver) -> None:
    _assert_page_loaded(driver, title_contains="fpscanner")
    _, body = _page_content(driver)
    failures = _fpscanner_failures(body)
    assert not failures, (
        f"FPScanner bot checks failed: {failures} "
        f"(body excerpt: {body[body.lower().find('bot detection') : body.lower().find('bot detection') + 1200]!r})"
    )


def _rebrowser_detections(driver) -> list[dict]:
    return (
        driver.execute_script(
            """
            const el = document.getElementById('detections-json');
            if (!el || !el.value) return [];
            try { return JSON.parse(el.value); } catch { return []; }
            """
        )
        or []
    )


def _rebrowser_failures(detections: list[dict]) -> list[str]:
    failures: list[str] = []
    for item in detections:
        name = item.get("type") or "?"
        rating = item.get("rating", 1)
        note = (item.get("note") or "").strip()

        if name in REBROWSER_OPTIONAL_NEUTRAL:
            if rating >= 1:
                failures.append(f"{name} failed (rating={rating}, note={note[:160]!r})")
            continue

        if rating >= 0:
            failures.append(f"{name} not green (rating={rating}, note={note[:160]!r})")
    return failures


def _trigger_rebrowser_optional_checks(driver) -> None:
    driver.execute_script(
        """
        if (typeof window.dummyFn === 'function') {
          window.dummyFn();
        }
        document.getElementById('detections-json');
        """
    )


def _wait_for_rebrowser_detections(driver) -> list[dict]:
    def ready(d) -> bool:
        detections = _rebrowser_detections(d)
        if len(detections) < 8:
            return False
        return not _rebrowser_failures(detections)

    _wait(driver).until(ready)
    return _rebrowser_detections(driver)


def _sannysoft_results(driver) -> dict:
    return driver.execute_script(
        """
            const normalize = (text) => (text || '').replace(/\\s+/g, ' ').trim();
            const cellStatus = (cell) => {
              if (!cell) return 'neutral';
              if (cell.classList.contains('failed')) return 'failed';
              if (cell.classList.contains('warn')) return 'warn';
              if (cell.classList.contains('passed')) return 'passed';
              return 'neutral';
            };

            const intoli = [];
            const intoliTable = document.querySelector('table');
            if (intoliTable) {
              for (const row of intoliTable.querySelectorAll('tr')) {
                const cells = [...row.querySelectorAll('td')];
                if (cells.length < 2) continue;
                const resultCell = cells[1];
                intoli.push({
                  name: normalize(cells[0].innerText),
                  result: normalize(resultCell.innerText),
                  status: cellStatus(resultCell),
                });
              }
            }

            const fpscanner = [];
            const fpTable = document.getElementById('fp2');
            if (fpTable) {
              for (const row of fpTable.querySelectorAll('tr')) {
                const cells = [...row.querySelectorAll('td')];
                if (cells.length < 2) continue;
                fpscanner.push({
                  name: normalize(cells[0].innerText),
                  status: normalize(cells[1].innerText).toLowerCase(),
                });
              }
            }

            return { intoli, fpscanner };
            """
    ) or {"intoli": [], "fpscanner": []}


def _sannysoft_scans_complete(results: dict) -> bool:
    fpscanner = results.get("fpscanner") or []
    fpscanner_names = {row.get("name") for row in fpscanner}
    if SANNY_SOFT_FPSCANNER_LAST not in fpscanner_names:
        return False

    intoli = results.get("intoli") or []
    webdriver = next(
        (
            row
            for row in intoli
            if row.get("name", "").startswith("WebDriver")
            and "Advanced" not in row.get("name", "")
        ),
        None,
    )
    if not webdriver:
        return False

    result = (webdriver.get("result") or "").lower()
    return result not in {"", "present (failed)"}


def _sannysoft_failures(results: dict) -> list[str]:
    failures: list[str] = []

    for row in results.get("intoli") or []:
        name = row.get("name") or "?"
        result = row.get("result") or ""
        status = row.get("status") or "neutral"

        if status == "failed":
            failures.append(f"Intoli {name}: {result}")
            continue
        if status == "warn":
            failures.append(f"Intoli {name}: warn ({result})")
            continue
        if "headlesschrome" in result.lower():
            failures.append(f"Intoli {name}: HeadlessChrome in user agent")

    for row in results.get("fpscanner") or []:
        name = row.get("name") or "?"
        status = (row.get("status") or "").lower()
        if status != "ok":
            failures.append(f"FPScanner {name}: {status or 'missing status'}")

    return failures


def _wait_for_sannysoft_results(driver) -> dict:
    def ready(d) -> bool:
        return _sannysoft_scans_complete(_sannysoft_results(d))

    _wait(driver).until(ready)
    return _sannysoft_results(driver)


def _assert_sannysoft_clean(driver) -> None:
    _assert_page_loaded(driver)
    results = _wait_for_sannysoft_results(driver)
    failures = _sannysoft_failures(results)
    assert not failures, f"bot.sannysoft.com failures: {failures}"


def test_bot_sannysoft(chrome_driver):
    chrome_driver.get(SANNY_SOFT_URL)
    _wait_for_page_ready(chrome_driver)
    _assert_sannysoft_clean(chrome_driver)


def test_bot_rebrowser(chrome_driver):
    chrome_driver.get(REBROWSER_TEST_URL)
    _wait(chrome_driver).until(
        lambda d: d.execute_script("return typeof window.dummyFn === 'function'")
    )
    _trigger_rebrowser_optional_checks(chrome_driver)
    detections = _wait_for_rebrowser_detections(chrome_driver)
    failures = _rebrowser_failures(detections)
    assert not failures, f"rebrowser-bot-detector failures: {failures}"


def test_bot_akamai(chrome_driver):
    chrome_driver.get("https://www.hilton.com/en/")
    _wait_for_page_ready(chrome_driver, title_contains="hilton")
    _assert_page_loaded(chrome_driver, title_contains="hilton")


def test_bot_fpscanner(chrome_driver):
    chrome_driver.get("https://fpscanner.com/demo/")
    _wait(chrome_driver).until(
        EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Bot Detection")
    )
    _assert_fpscanner_clean(chrome_driver)


def test_untrace_extension(chrome_driver):
    def _extensions_page(driver):
        return driver.execute_script("""
        const manager = document.querySelector('extensions-manager');
        if (!manager || !manager.shadowRoot) return { items: [], text: '' };
        const list = manager.shadowRoot.querySelector('extensions-item-list');
        const items = [];
        let text = manager.shadowRoot.textContent || '';
        if (list && list.shadowRoot) {
          text += '\\n' + (list.shadowRoot.textContent || '');
          for (const item of list.shadowRoot.querySelectorAll('extensions-item')) {
            if (!item.shadowRoot) continue;
            const nameEl = item.shadowRoot.querySelector('#name');
            const name = nameEl ? nameEl.textContent.trim() : '';
            const body = item.shadowRoot.textContent || '';
            items.push({ name, body, id: item.id || '' });
            text += '\\n' + body;
          }
        }
        return { items, text };
        """)

    chrome_driver.get("chrome://extensions/")
    _wait(chrome_driver).until(
        lambda d: any(
            "untrace" in (item.get("name") or "").lower()
            or "mgnlenokophofdnmlabkgpmlnolgomgj" in (item.get("id") or "")
            for item in (_extensions_page(d).get("items") or [])
        )
    )

    page = _extensions_page(chrome_driver)
    items = page.get("items") or []
    page_text = (page.get("text") or "").strip()

    assert page_text, "chrome://extensions/ page content should not be empty"

    page_lower = page_text.lower()
    for marker in BLOCKED_MARKERS:
        assert marker not in page_lower, (
            f"chrome://extensions/ shows an error ({marker!r}): {page_text[:400]!r}"
        )

    untrace_items = [
        item for item in items if "untrace" in (item.get("name") or "").lower()
    ]
    assert untrace_items, (
        f"Untrace Injector not listed on chrome://extensions/: {items}"
    )

    item_text = (untrace_items[0].get("body") or "").lower()
    for phrase in (
        "activez le mode développeur",
        "enable developer mode",
    ):
        assert phrase not in item_text and phrase not in page_lower, (
            f"Extension should load without an activation prompt, found '{phrase}'"
        )
