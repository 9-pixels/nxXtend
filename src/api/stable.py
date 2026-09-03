import requests
from src.models.package import Package

# NixOS Search API endpoint for stable channel
URL = "https://search.nixos.org/backend/latest-48-nixos-26.05/_search"
HEADERS = {
    "Content-Type": "application/json",
    # Base64 encoded credentials — move to environment variable before production
    "Authorization": "Basic YVdWU0FMWHBadjpYOGdQSG56TDUyd0ZFZWt1eHNmUTljU2g="
}

def stable_search(pkg_name: str) -> list[Package]:
    """Search for packages in the nixpkgs stable channel via nixos.org API."""
    response = requests.post(URL, headers=HEADERS, json={
    "query": {"multi_match": {"query": pkg_name, "fields": ["package_attr_name", "package_pname", "package_description"]}},
    "size": 500
    })

    data = response.json()
    packages = []
    for hit in data["hits"]["hits"]:
        source = hit["_source"]
        packages.append(Package(
            name=source["package_pname"],
            version=source["package_pversion"],
            description=source["package_description"],
            source="stable",
            type=None,
            attribute=source["package_attr_name"]

        ))
    return packages

