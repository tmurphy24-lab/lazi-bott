from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
import os

p = ChromeDriverManager().install()
folder = os.path.dirname(p)
chrome_path = os.path.join(folder, "chromedriver.exe")

opts = webdriver.ChromeOptions()
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-dev-shm-usage")
opts.add_argument("--disable-gpu")
opts.add_argument(r"--user-data-dir=C:\Users\trevo\AppData\Local\Google\Chrome\User Data")
opts.add_argument("--profile-directory=Profile 11")
opts.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
try:
    d = webdriver.Chrome(service=ChromeService(chrome_path), options=opts)
    print("LAUNCH OK with profile, title=", repr(d.title))
    d.quit()
except Exception as e:
    print("LAUNCH FAILED with profile:", type(e).__name__, str(e)[:500])
