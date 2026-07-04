import pytest

from dockrice import DockerPath
from dockrice.dockerpath import MountOption
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


@pytest.mark.parametrize("arg", ["./", ".", Path("./"), Path(".")])
@pytest.mark.parametrize("mount_parent", [True, False, None])
def test_current_dir_mount_target_source_aligned(arg, mount_parent):
    # './' is a relative path whose unresolved parent is itself ('.') and whose
    # unresolved name is empty. Both target and source must be derived from the
    # resolved path so the bind mount stays aligned.
    path = DockerPath(arg, mount_parent=mount_parent)
    target, source = path._get_target_source()
    cwd = Path.cwd()
    if path.mount_parent:
        assert target == str(cwd.parent)
        assert source == str(cwd.parent)
    else:
        assert target == str(cwd)
        assert source == str(cwd)


@pytest.mark.parametrize("mount_parent", [True, False])
def test_current_dir_custom_mount_path(mount_parent):
    path = DockerPath("./", mount_path="/data", mount_parent=mount_parent)
    cwd = Path.cwd()
    if mount_parent:
        # parent mounted; the dir name is appended to the mount path
        assert str(path.mount_path) == f"/data/{cwd.name}"
    else:
        assert str(path.mount_path) == "/data"
