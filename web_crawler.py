
import sys
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from typing import Any
import random


class BaseWebCrawler:
    def __init__(self, lang="zh-TW", headless=False):
        options = uc.ChromeOptions()
        options.add_argument(f"--lang={lang}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36")
        options.add_argument("--disable-infobars")
        options.add_argument("--start-maximized")
        if headless:
            options.add_argument("--headless")
        self.driver = uc.Chrome(options=options)
        self.driver.implicitly_wait(10)
        self.driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    def random_mouse_move(self, body, times=5):
        win_rect = self.driver.get_window_rect()
        win_width = win_rect['width']
        win_height = win_rect['height']
        for _ in range(times):
            x = random.randint(0, max(0, win_width-10))
            y = random.randint(0, max(0, win_height-10))
            try:
                ActionChains(self.driver).move_to_element_with_offset(
                    body, x, y).perform()
            except Exception:
                pass

    def close(self):
        self.driver.quit()


class GoogleCrawler(BaseWebCrawler):
    def search(self, query, pages=2):
        results = []
        self.driver.get('https://www.google.com/')
        search = self.driver.find_element(By.NAME, 'q')
        body = self.driver.find_element(By.TAG_NAME, 'body')
        self.random_mouse_move(body, times=random.randint(3, 8))
        ActionChains(self.driver).move_to_element(search).click().perform()
        for char in query:
            search.send_keys(char)
        search.send_keys(Keys.ENTER)
        for _ in range(pages):
            items = self.driver.find_elements(By.CLASS_NAME, "LC20lb")
            addrs = self.driver.find_elements(By.CLASS_NAME, "yuRUbf")
            for item, addr in zip(items, addrs):
                url = addr.find_element(By.TAG_NAME, 'a').get_attribute('href')
                results.append({'title': item.text, 'url': url})
            self.random_mouse_move(body, times=random.randint(2, 6))
            try:
                next_btn = self.driver.find_element(By.ID, 'pnnext')
                ActionChains(self.driver).move_to_element(
                    next_btn).click().perform()
            except NoSuchElementException:
                break
        return results


def google_search(search_string: str = 'python') -> list[Any]:
    crawler = GoogleCrawler()
    try:
        return crawler.search(search_string)
    finally:
        crawler.close()


def browser_website(url: str) -> str:
    """
    開啟指定網站並隨機移動滑鼠，回傳該網站 HTML 內容。
    """

    crawler = BaseWebCrawler()
    html = ""
    try:
        crawler.driver.get(url)
        body = crawler.driver.find_element(By.TAG_NAME, 'body')
        crawler.random_mouse_move(body, times=random.randint(3, 8))
        WebDriverWait(crawler.driver, 10).until(
            lambda d: d.execute_script(
                'return document.readyState') == 'complete'
        )
        html = crawler.driver.page_source
    except Exception:
        pass
    finally:
        try:
            crawler.close()
        except Exception:
            pass
    return html


# 可直接 import google_search 使用
print(google_search('python'))  # Example usage, can be removed later
print(google_search('selenium'))
print(browser_website('https://www.wikipedia.org/'))  # 範例，可移除
