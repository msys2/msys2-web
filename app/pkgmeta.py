# Copyright 2023 Christoph Reiter
# SPDX-License-Identifier: MIT

import yaml
from pydantic import BaseModel, Field
from typing import Dict, Optional


class PkgMetaEntry(BaseModel):

    internal: bool = Field(default=False)
    """If the package is MSYS2 internal or just a meta package"""

    references: Dict[str, Optional[str]] = Field(default_factory=dict)
    """References to third party repositories"""


class PkgMeta(BaseModel):

    packages: Dict[str, PkgMetaEntry]
    """A mapping of pkgbase names to PkgMetaEntry"""


def parse_yaml(data: bytes) -> PkgMeta:
    """Parse a YAML string into a PkgMeta object"""

    return PkgMeta.model_validate(yaml.safe_load(data))
