# Copyright 2023 Christoph Reiter
# SPDX-License-Identifier: MIT

from pydantic import BaseModel, Field
from collections.abc import Sequence, Collection


class PkgExtraEntry(BaseModel):
    """Extra metadata for a PKGBUILD"""

    internal: bool = Field(default=False)
    """If the package is MSYS2 internal or just a meta package"""

    references: dict[str, str | None] = Field(default_factory=dict)
    """References to third party repositories"""

    changelog_url: str | None = Field(default=None)
    """A NEWS file in git or the github releases page.
    In case there are multiple, the one that is more useful for packagers
    """

    documentation_url: str | None = Field(default=None)
    """Documentation for the API, tools, etc provided, in case it's a different
    website"""

    repository_url: str | None = Field(default=None)
    """Web view of the repository, e.g. on github or gitlab"""

    issue_tracker_url: str | None = Field(default=None)
    """The bug tracker, mailing list, etc"""

    pgp_keys_url: str | None = Field(default=None)
    """A website containing which keys are used to sign releases"""


class PkgExtra(BaseModel):

    packages: dict[str, PkgExtraEntry]
    """A mapping of pkgbase names to PkgExtraEntry"""


def convert_mapping(array: Sequence[str]) -> dict[str, str | None]:
    converted: dict[str, str | None] = {}
    for item in array:
        if ":" in item:
            key, value = item.split(":", 1)
            value = value.strip()
        else:
            key = item
            value = None
        converted[key] = value
    return converted


def extra_to_pkgextra_entry(data: dict[str, str | Collection[str]]) -> PkgExtraEntry:
    mappings = ["references"]

    data = dict(data)
    for key in mappings:
        if key in data:
            value = data[key]
            assert isinstance(value, list)
            data[key] = convert_mapping(value)

    entry = PkgExtraEntry.model_validate(data)
    return entry
