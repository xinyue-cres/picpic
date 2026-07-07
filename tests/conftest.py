import pathlib
import pytest


@pytest.fixture
def tmp_db_path(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "picpic.db"


@pytest.fixture
def anyio_backend():
    return "asyncio"
