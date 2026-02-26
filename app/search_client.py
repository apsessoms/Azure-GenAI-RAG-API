from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

def build_search_client(endpoint: str, index_name: str, api_key: str) -> SearchClient:
    return SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(api_key),
    )