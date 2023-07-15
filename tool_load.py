from trafilatura import extract, fetch_url
from trafilatura.settings import use_config

from shared import debug

trafilatura_config = use_config()
trafilatura_config.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")


def load_webpage(url: str) -> str:
    if debug():
        print(f"load_webpage called {url}")

    downloaded = fetch_url(url)
    url_content = extract(downloaded, include_links=True, config=trafilatura_config)

    if not url_content:
        url_content = "Failed to load url, maybe you can try another?"

    return url_content
