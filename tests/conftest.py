import time

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

POST_TEST_DELAY = 20

HEADLESS = False


@pytest.fixture
def chrome_driver():
    options = Options()
    options.page_load_strategy = "none"
    if HEADLESS:
        options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    try:
        yield driver
    finally:
        time.sleep(POST_TEST_DELAY)
        driver.quit()
