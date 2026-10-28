import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
import yt_dlp
import tempfile
import os
import time

log = logging.getLogger(__name__)

GECKO_PATH = r"C:\geckodriver.exe"

#==================================================================================================================================================================================
def yt_search(query: str):
    """Uses Selenium to get the first real YouTube video URL + reject cookies."""
    # --- setup browser ---
    opts = Options()
    opts.add_argument("--headless")
    service = Service(executable_path=GECKO_PATH)
    driver = webdriver.Firefox(service=service, options=opts)
    driver.get("https://www.youtube.com")
    time.sleep(3)  # wait for page load

    #try reject cookies if it shows up
    try:
        try:
            reject_cookies_btn = driver.find_element(
                By.XPATH,
                "/html/body/ytd-app/ytd-consent-bump-v2-lightbox/tp-yt-paper-dialog/div[4]/div[2]/div[6]/div[1]/ytd-button-renderer[1]/yt-button-shape/button/yt-touch-feedback-shape",
            )
            reject_cookies_btn.click()
            log.info("Rejected cookies")
            time.sleep(2)
        except Exception:
            log.info("No cookie popup or selector not found")

        #search for the video
        search_box = driver.find_element(By.NAME, "search_query")
        search_box.send_keys(query)
        time.sleep(1)
        search_box.submit()
            
        log.info("Searching for: %r", query)
        time.sleep(3)  #wait for results

        #get first video (skip ads)
        videos = driver.find_elements(By.XPATH, "//ytd-video-renderer//a[@id='video-title']")
        if not videos:
            log.warning("No video elements found.")
            return None, None

        first_url = videos[0].get_attribute("href")
        log.info("Found video: %r", first_url)

        #return URL and cookies and close driver
        cookies = driver.get_cookies()
        return first_url, cookies
    finally:
        driver.quit()

#==================================================================================================================================================================================
def save_selenium_cookies(cookies, path):
    """Convert Selenium cookies to Netscape format for yt-dlp."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for c in cookies:
            domain = c.get("domain", "")
            include_subs = "TRUE" if domain.startswith(".") else "FALSE"
            path_ = c.get("path", "/")
            secure = "TRUE" if c.get("secure", False) else "FALSE"
            expires = str(c.get("expiry", 0))
            name = c.get("name", "")
            value = c.get("value", "")
            f.write(
                "\t".join([domain, include_subs, path_, secure, expires, name, value])
                + "\n"
            )
    log.info("Saved cookies to: %r", path)

#==================================================================================================================================================================================

def download_audio_with_ytdlp(video_url, cookie_file):
    # Match Firefox User-Agent
    ydl_opts = {
    "format": "bestaudio/best",
    "outtmpl": "%(title)s.%(ext)s",
    "quiet": False,
    "cookiefile": cookie_file,
    "noplaylist": True,
    "postprocessors": [
        {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
        {"key": "FFmpegMetadata"},
    ],
    "ffmpeg_location": r"C:\CODE_FOLDER\Python\Virtual_Environments\Python_DiscordBot\discordENV2\bin\ffmpeg",
    # Force using SDKless player clients (what the CLI did)
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web_safari"]
        }
    }
}
    log.info("Starting download for: %r", video_url)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        log.info("Download complete: %r", info.get('title', 'Unknown Title'))

#==================================================================================================================================================================================
if __name__ == "__main__":
    try:
        q = input("Enter search query: ")
        url, cookies = yt_search(q)

        if not url:
            log.warning("Could not find video.")
        else:
            # Save cookies to temp file
            tmp_cookiefile = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
            save_selenium_cookies(cookies, tmp_cookiefile)

            # Download using yt-dlp
            download_audio_with_ytdlp(url, tmp_cookiefile)
    except Exception as e:
        log.exception("Test run failed")