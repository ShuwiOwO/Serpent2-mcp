import pytest

from serpent2_mcp.lint import Index


@pytest.fixture(scope="session")
def index() -> Index:
    return Index.from_static()


@pytest.fixture()
def fixtures_dir():
    from pathlib import Path

    return Path(__file__).parent / "fixtures"
