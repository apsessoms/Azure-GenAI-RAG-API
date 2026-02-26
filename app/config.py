import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    search_endpoint: str
    search_index_name: str
    search_api_key: str

    aoai_endpoint: str
    aoai_api_key: str
    aoai_deployment: str

def get_settings() -> Settings:
    return Settings(
        search_endpoint=os.environ["SEARCH_ENDPOINT"],
        search_index_name=os.environ["SEARCH_INDEX_NAME"],
        search_api_key=os.environ["SEARCH_API_KEY"],

        aoai_endpoint=os.environ["AOAI_ENDPOINT"],
        aoai_api_key=os.environ["AOAI_API_KEY"],
        aoai_deployment=os.environ["AOAI_DEPLOYMENT"],
    )