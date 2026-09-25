import requests
from api.api_config import UNSTABLE_URL, HEADERS
from models.package import Package


def unstable_search(pkg_name: str) -> list[Package]:
    """Search for packages in the nixpkgs unstable channel via nixos.org API."""
    response = requests.post(UNSTABLE_URL, headers=HEADERS, json={
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
            attribute=unstable["package_pname"]

        ))
    return packages
