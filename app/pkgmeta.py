# Copyright 2023 Christoph Reiter
# SPDX-License-Identifier: MIT

import yaml
from pydantic import BaseModel, Field
from typing import Dict, Optional


class PkgMetaEntry(BaseModel):
    """Extra metadata for a PKGBUILD"""

    internal: bool = Field(default=False)
    """If the package is MSYS2 internal or just a meta package"""

    references: Dict[str, Optional[str]] = Field(default_factory=dict)
    """References to third party repositories"""

    changelog_url: Optional[str] = Field(default=None)
    """A NEWS file in git or the github releases page.
    In case there are multiple, the one that is more useful for packagers
    """

    documentation_url: Optional[str] = Field(default=None)
    """Documentation for the API, tools, etc provided, in case it's a different
    website"""

    repository_url: Optional[str] = Field(default=None)
    """Web view of the repository, e.g. on github or gitlab"""

    issue_tracker_url: Optional[str] = Field(default=None)
    """The bug tracker, mailing list, etc"""

    pgp_keys_url: Optional[str] = Field(default=None)
    """A website containing which keys are used to sign releases"""


class PkgMeta(BaseModel):

    packages: Dict[str, PkgMetaEntry]
    """A mapping of pkgbase names to PkgMetaEntry"""


def parse_yaml(data: bytes) -> PkgMeta:
    """Parse a YAML string into a PkgMeta object"""

    return PkgMeta.model_validate(yaml.safe_load(data))
