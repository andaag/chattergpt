from functools import lru_cache

from pydantic import BaseModel, Field
from trafilatura import extract, fetch_url
from trafilatura.settings import use_config

from shared import debug

trafilatura_config = use_config()
trafilatura_config.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")


class LoadWebpageUrl(BaseModel):
    url: str = Field(
        description="A valid url to load. You must:\n - Use search to find the url\n - Then use load_webpage(with url from search)"
    )


@lru_cache(maxsize=20)
def load_webpage(url: str) -> str:
    if debug():
        print(f"load_webpage called {url}")

    downloaded = fetch_url(url)
    url_content = extract(downloaded, include_links=True, config=trafilatura_config)

    if not url_content:
        url_content = "ERROR : Failed to load url."

    return url_content
