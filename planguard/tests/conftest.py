from __future__ import annotations

from pathlib import Path

import pytest

from planguard.plan import Plan

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_plan():
    """load_plan("05-nat-shared-vpc") -> Plan, from the real plan fixtures."""

    def _load(name: str) -> Plan:
        return Plan.load(FIXTURES / f"{name}.json")

    return _load
