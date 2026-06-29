import time

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

PAGE_LOAD_WAIT = 15


@pytest.fixture
def chrome_driver():
    driver = webdriver.Chrome(options=Options())
    try:
        yield driver
    finally:
        time.sleep(PAGE_LOAD_WAIT)
        driver.quit()
