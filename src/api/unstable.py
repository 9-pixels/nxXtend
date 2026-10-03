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

        # `attribute` is the canonical Nix identity: package_attr_name already
        # carries the full attribute path (e.g. "python314Packages.foo"), so
        # package_attr_set must not be prepended again. A record without it
        # cannot yield a valid Nix reference — skip it rather than falling back
        # to package_pname, which is a different identity (pname != attribute).
        attribute = unstable.get("package_attr_name")
        if not attribute:
            continue

        packages.append(Package(
            name=unstable["package_pname"],
            version=unstable["package_pversion"],
            description=unstable["package_description"],
            source="unstable",
            type=None,
            attribute=attribute
        ))
    return packages
