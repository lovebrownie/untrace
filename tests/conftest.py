import os
import time

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from untrace import injector

PAGE_LOAD_WAIT = 15


def pytest_addoption(parser):
    parser.addoption(
        "--headless",
        action="store_true",
        default=False,
        help="Run Chrome in headless mode (the only allowed pytest CLI option)",
    )


@pytest.fixture
def chrome_driver(request):
    untrace_bin = str(injector.USER_UNTRACE_ROOT)
    wrapper = injector.USER_UNTRACE_ROOT / "chrome"
    if wrapper.is_file():
        os.environ["SE_CHROME_BINARY"] = str(wrapper)
        os.environ["PATH"] = f"{untrace_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    options = Options()
    if request.config.getoption("--headless"):
        options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    try:
        yield driver
    finally:
        time.sleep(PAGE_LOAD_WAIT)
        driver.quit()