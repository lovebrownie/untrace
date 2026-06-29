import time

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

PAGE_LOAD_WAIT = 15
HEADLESS = False


@pytest.fixture
def chrome_driver():
    options = Options()
    if HEADLESS:
        options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    try:
        yield driver
    finally:
        time.sleep(PAGE_LOAD_WAIT)
        driver.quit()
