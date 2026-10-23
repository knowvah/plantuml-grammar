"""Shared fixtures: real I2 shape via ``load_dir`` + ``resolve`` on toy YAML models."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def models() -> ResolvedModels:
    return resolve(load_dir(FIXTURES))
