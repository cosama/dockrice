import pytest

from dockrice import DockerPath
from pathlib import PurePath, Path


@pytest.mark.parametrize(
    "arg1, arg2",
    [
        ("test/path", None),
        ("test/path", "another/path"),
        (Path("existing/path"), None),
        (Path("existing/path"), "string/path"),
        ("string/path", Path("existing/path")),
    ],
)
def test_path_initialization(arg1, arg2):
    if arg2 is None:
        path = DockerPath(arg1)
    else:
        path = DockerPath(arg1, arg2)

    path.resolve()
    path.exists()
    assert isinstance(path, PurePath)
    assert isinstance(path.mount_path, PurePath)
