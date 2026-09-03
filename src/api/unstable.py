import requests
from src.models.package import Package

# NixOS Search API endpoint for unstable channel
URL = "https://search.nixos.org/backend/latest-48-nixos-unstable/_search"
HEADERS = {
    "Content-Type": "application/json",
    # Base64 encoded credentials — move to environment variable before production
    "Authorization": "Basic YVdWU0FMWHBadjpYOGdQSG56TDUyd0ZFZWt1eHNmUTljU2g="
}

def unstable_search(pkg_name: str) -> list[Package]:
    """Search for packages in the nixpkgs unstable channel via nixos.org API."""
    response = requests.post(URL, headers=HEADERS, json={
    "query": {"multi_match": {"query": pkg_name, "fields": ["package_attr_name", "package_pname", "package_description"]}},
    "size": 500
    })

    data = response.json()
    packages = []
    for hit in data["hits"]["hits"]:
        unstable = hit["_source"]
        packages.append(Package(
            name=unstable["package_pname"],
            version=unstable["package_pversion"],
            description=unstable["package_description"],
            source="unstable",
            type=None,
            attribute=unstable["package_attr_name"]

        ))
    return packages

