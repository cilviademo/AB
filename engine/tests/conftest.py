import pytest

from ab_engine import api
from ab_engine.workspace import Workspace

# Stage packages register their RPC methods on import, as the server and CLI do.
api._load_stage_modules()


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return Workspace.open(tmp_path / "ws")
