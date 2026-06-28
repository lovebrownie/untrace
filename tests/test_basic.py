from selenium import webdriver
from selenium.webdriver.chrome.options import Options


def test_basic():
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)

    driver.get("https://example.com")
    title = driver.title

    driver.quit()

    assert title, "Title should not be empty"
