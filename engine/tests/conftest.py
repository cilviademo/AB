import pytest

from ab_engine.workspace import Workspace


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return Workspace.open(tmp_path / "ws")
