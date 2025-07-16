import sys
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from typing import Any
import time
import random


def google_search(search_string: str = 'python') -> list[Any]:
    results = []
    try:
        options = uc.ChromeOptions()
        options.add_argument("--lang=zh-TW")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36")
        options.add_argument("--disable-infobars")
        options.add_argument("--start-maximized")
        driver = uc.Chrome(options=options)
        driver.implicitly_wait(10)
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.get('https://www.google.com/')
        time.sleep(random.uniform(2, 4))
        # print(driver.title)
        # html = driver.page_source

        try:
            search = driver.find_element(By.NAME, 'q')
            body = driver.find_element(By.TAG_NAME, 'body')
            win_rect = driver.get_window_rect()
            win_width = win_rect['width']
            win_height = win_rect['height']
            for _ in range(random.randint(3, 8)):
                x = random.randint(0, max(0, win_width-10))
                y = random.randint(0, max(0, win_height-10))
                try:
                    ActionChains(driver).move_to_element_with_offset(
                        body, x, y).perform()
                except Exception:
                    pass
                time.sleep(random.uniform(0.1, 0.4))
            ActionChains(driver).move_to_element(search).click().perform()
            time.sleep(random.uniform(0.8, 1.5))
            for char in search_string:
                search.send_keys(char)
                time.sleep(random.uniform(0.1, 0.3))
            time.sleep(random.uniform(0.8, 1.5))
            search.send_keys(Keys.ENTER)
            time.sleep(random.uniform(2, 4))

            for page in range(2):
                items = driver.find_elements(By.CLASS_NAME, "LC20lb")
                addrs = driver.find_elements(By.CLASS_NAME, "yuRUbf")
                all = zip(items, addrs)
                for item in all:
                    addr = item[1].find_element(
                        By.TAG_NAME, 'a').get_attribute('href')
                    results.append({'title': item[0].text, 'url': addr})
                win_rect = driver.get_window_rect()
                win_width = win_rect['width']
                win_height = win_rect['height']
                for _ in range(random.randint(2, 6)):
                    x = random.randint(0, max(0, win_width-10))
                    y = random.randint(0, max(0, win_height-10))
                    try:
                        ActionChains(driver).move_to_element_with_offset(
                            body, x, y).perform()
                    except Exception:
                        pass
                    time.sleep(random.uniform(0.1, 0.4))
                try:
                    next_btn = driver.find_element(By.ID, 'pnnext')
                    ActionChains(driver).move_to_element(
                        next_btn).click().perform()
                    time.sleep(random.uniform(2, 4))
                except NoSuchElementException:
                    break
        except Exception:
            pass
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    except Exception:
        return []
    return results


# 可直接 import google_search 使用
print(google_search('python'))  # Example usage, can be removed later
