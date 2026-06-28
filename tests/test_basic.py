import time

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options


@pytest.fixture
def chrome_driver():
    options = Options()
    driver = webdriver.Chrome(options=options)
    try:
        yield driver
    finally:
        time.sleep(12)
        driver.quit()


def test_bot_sannysoft_loads(chrome_driver):
    chrome_driver.get("https://bot.sannysoft.com/")
    time.sleep(5)
    assert chrome_driver.title, "Title should not be empty"


def test_untrace_extension_listed_on_chrome_extensions(chrome_driver):
    chrome_driver.get("chrome://extensions/")
    time.sleep(5)

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
    page_text = (page.get("text") or "").lower()

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
        assert phrase not in item_text and phrase not in page_text, (
            f"Extension should load without an activation prompt, found '{phrase}'"
        )
