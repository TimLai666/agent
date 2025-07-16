import random
import os
import undetected_chromedriver as uc
from typing import Any
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from pydantic_ai import Agent


def add_website_tools(agent: Agent) -> None:
    """Add website-related tools to the agent."""

    @agent.tool_plain
    def google_search(search_string: str) -> list[Any]:
        """
        Search Google and return a list of results.
        Use this tool for searching the web.
        """
        crawler = GoogleCrawler()
        try:
            return crawler.search(search_string)
        finally:
            crawler.close()

    @agent.tool_plain
    def browse_website(url: str) -> str:
        """
        Open a specified website and return the cleaned main text content.
        Use this tool to go into a web page and read the content.
        """
        from bs4 import BeautifulSoup

        html = ""
        with BaseWebCrawler() as crawler:
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
        # 用 BeautifulSoup 清理成 AI 容易理解的格式
        soup = BeautifulSoup(html, "html.parser")
        # 只取主要文字內容
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
        text = soup.get_text(separator='\n', strip=True)
        # 移除多餘空行
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned_text = '\n'.join(lines)
        return cleaned_text


class BaseWebCrawler:
    def __init__(self, lang="zh-TW", headless=False):
        # 自動清理 undetected_chromedriver 目標檔案，避免 FileExistsError
        try:
            user_dir = os.path.expanduser("~")
            base_dir = os.path.join(
                user_dir, "appdata", "roaming", "undetected_chromedriver")
            exe1 = os.path.join(base_dir, "undetected_chromedriver.exe")
            exe2 = os.path.join(base_dir, "undetected",
                                "chromedriver-win32", "chromedriver.exe")
            for f in [exe1, exe2]:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
        except Exception:
            pass
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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.close()
        except Exception:
            pass

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
