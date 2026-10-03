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

        # `attribute` is the canonical Nix identity: package_attr_name already
        # carries the full attribute path (e.g. "python314Packages.foo"), so
        # package_attr_set must not be prepended again. A record without it
        # cannot yield a valid Nix reference — skip it rather than falling back
        # to package_pname, which is a different identity (pname != attribute).
        attribute = source.get("package_attr_name")
        if not attribute:
            continue

        packages.append(Package(
            name=source["package_pname"],
            version=source["package_pversion"],
            description=source["package_description"],
            source="stable",
            type=None,
            attribute=attribute
        ))
    return packages
