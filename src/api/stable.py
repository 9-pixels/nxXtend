import requests
from api.api_config import STABLE_URL, HEADERS
from models.package import Package


def stable_search(pkg_name: str) -> list[Package]:
    """Search for packages in the nixpkgs stable channel via nixos.org API."""
    response = requests.post(STABLE_URL, headers=HEADERS, json={
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
            attribute=source["package_pname"]
        ))
    return packages
