import json
import os

import requests
from pydantic import BaseModel, Field

from shared import debug


class SearchQuery(BaseModel):
    query: str = Field(description="The query to search for")


def search(query: str):
    """Searches the internet for a query.

    Parameters
    ----------
    query : string
        The query to search for.
    """

    def _search(query):
        if debug():
            print(f"Search called {query}")
        url = "https://google.serper.dev/search"

        payload = json.dumps({"q": query})
        headers = {
            "X-API-KEY": os.environ["SERPER_API_KEY"],
            "Content-Type": "application/json",
        }

        response = requests.request("POST", url, headers=headers, data=payload)
        return response.json()

    results = _search(query)
    snippets = [v for v in results["organic"] if "youtube" not in v["link"]]
    # if "answerBox" in results:
    #    snippets = [
    #        {
    #            "snippet": results["answerBox"]["title"]
    #            + "="
    #            + results["answerBox"]["answer"]
    #        }
    #    ] + snippets
    return json.dumps(snippets[0:5])
