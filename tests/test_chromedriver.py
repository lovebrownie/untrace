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


def _wait(driver) -> WebDriverWait:
    return WebDriverWait(driver, PAGE_TIMEOUT)


def _page_has_content(driver) -> bool:
    try:
        return bool(
            driver.execute_script(
                """
                if (document.readyState !== 'complete') return false;
                const title = (document.title || '').trim();
                const body = (document.body && document.body.innerText || '').trim();
                return title.length > 0 || body.length > 0;
                """
            )
        )
    except Exception:
        return False


def _wait_for_page_ready(driver) -> None:
    _wait(driver).until(_page_has_content)


def _page_content(driver) -> tuple[str, str]:
    title = (driver.title or "").strip()
    body = (driver.find_element(By.TAG_NAME, "body").text or "").strip()
    return title, body


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


def test_bot_sannysoft_loads(chrome_driver):
    chrome_driver.get("https://bot.sannysoft.com/")
    _wait_for_page_ready(chrome_driver)
    _assert_page_loaded(chrome_driver)


AKAMAI_TEST_URL = "https://www.hilton.com/en/"


def test_bot_akamai_loads(chrome_driver):
    chrome_driver.get(AKAMAI_TEST_URL)
    _wait_for_page_ready(chrome_driver)
    _assert_page_loaded(chrome_driver, title_contains="hilton")


def test_fpscanner_demo_loads(chrome_driver):
    chrome_driver.get("https://fpscanner.com/demo/")
    _wait(driver).until(
        EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Bot Detection")
    )
    _assert_fpscanner_clean(chrome_driver)


def test_untrace_extension_listed_on_chrome_extensions(chrome_driver):
    chrome_driver.get("chrome://extensions/")
    _wait(driver).until(
        lambda d: d.execute_script("""
        const manager = document.querySelector('extensions-manager');
        return Boolean(manager && manager.shadowRoot);
        """)
    )

    page = chrome_driver.execute_script("""
    const manager = document.querySelector('extensions-manager');
    if (!manager || !manager.shadowRoot) return { items: [], text: '' };
    const list = manager.shadowRoot.querySelector('extensions-item-list');
    const items = [];
    let text = manager.shadowRoot.textContent || '';
    if (list && list.shadowRoot) {
      for (const item of list.shadowRoot.querySelectorAll('extensions-item')) {
        if (!item.shadowRoot) continue;
        const name = item.shadowRoot.querySelector('#name')?.textContent?.trim() || '';
        const body = item.shadowRoot.textContent || '';
        items.push({ name, body });
        text += '\\n' + body;
      }
    }
    return { items, text };
    """)
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