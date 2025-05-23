# Copyright (C) 2021 Marco Salathe (www.github.com/cosama/)

import pathlib
import uuid
from docker.types import Mount
from typing import Union, Tuple
from enum import Enum
import sys

PathLike = Union[pathlib.PurePath, str]


def remove_prefix(string, prefix):
    return string[(len(prefix) if string.startswith(prefix) else 0) :]


class MountOption(Enum):
    random = 0
    host = 1


class DockerPath(type(pathlib.Path())):
    def __new__(
        cls,
        *args,
        **__,
    ):
        """Needed to overwrite pathlib.Path. See __init__ for more docs."""
        return super().__new__(cls, *args)

    def __init__(
        self,
        *path,
        mount_path: Union[PathLike, MountOption] = MountOption.host,
        read_only: bool = False,
        mount_parent: Union[bool, None] = None,
    ) -> None:
        """Create a DockerPath object. DockerPath objects are immutable.

        Parameters
        ----------
        path: PathLike (identical to pathlib.Path creator)
            The host path.
        mount_path : [PathLike, MountOption], optional
            The path inside the docker container, CAUTION: If 'mount_parent' is true,
            this will be the parent path and path.name will be appended.
            There are two ways to automatically define the mount_path:
                MountOption.host:   Use the host path as mount_path.
                                    This might not work in all situations
                MountOption.random: Created as /temp/ + uuid + /path.name.
                                    This is safer and will always work.
        read_only : bool, optional
            Mount the path with read only access, by default False.
        mount_parent : Union[bool, None], optional
            Do not mount path itself, but it's parent instead, by default None.
            If None, will check if the path exist, if it does, this is set to False,
            if not it is set to True.
        """
        self._mount_path = mount_path
        self._mount_parent = mount_parent
        self._read_only = read_only
        if sys.version_info >= (3, 12):
            super().__init__(*path)

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def mount_parent(self) -> bool:
        if self._mount_parent is None:
            if self.resolve(strict=False).exists():
                mount_parent = False
            else:
                mount_parent = True
            return mount_parent
        return self._mount_parent

    @property
    def mount_path(self) -> pathlib.PurePosixPath:
        if self._mount_path == MountOption.host:
            # on windows self is a WindowsPath object, we need to mirror it into a
            # path valid in posix this includes removing the drive ("C:")
            mount_path = pathlib.PurePosixPath(
                remove_prefix(
                    self.resolve(strict=False).as_posix(),
                    self.resolve(strict=False).drive,
                )
            )
            # print(mount_path)
        elif self._mount_path == MountOption.random:
            mount_path = pathlib.PurePosixPath("/temp", str(uuid.uuid4()), self.name)
        else:
            mount_path = self._mount_path
            if isinstance(mount_path, tuple):
                mount_path = pathlib.PurePosixPath(*mount_path)
            else:
                mount_path = pathlib.PurePosixPath(mount_path)
            if self.mount_parent is True:
                mount_path = pathlib.PurePosixPath(mount_path, self.name)
        assert (
            mount_path.is_absolute()
        ), f"Require an absolute path for the mount path. Is '{mount_path}'."
        return mount_path

    def _get_target_source(self) -> Tuple[pathlib.PurePath]:
        if self.mount_parent:
            target = self.mount_path.parent
            source = self.parent
        else:
            target = self.mount_path
            source = self
        return str(target), str(source.resolve())

    def get_mount(self) -> Mount:
        target, source = self._get_target_source()
        return Mount(
            target,
            source,
            type="bind",
            read_only=self._read_only,
        )

    def get_mount_string(self) -> str:
        target, source = self._get_target_source()
        access_rights = "ro" if self._read_only else "rw"
        return f"{source}:{target}:{access_rights}"


class DockerPathFactory:
    """Simple class to  be used with argparsers"""

    def __init__(
        self,
        mount_path: Union[PathLike, MountOption] = MountOption.host,
        read_only: bool = False,
        mount_parent: Union[bool, None] = None,
    ):
        self.mount_path = mount_path
        self.read_only = read_only
        self.mount_parent = mount_parent

    def __call__(self, *path):
        return DockerPath(
            *path,
            mount_path=self.mount_path,
            read_only=self.read_only,
            mount_parent=self.mount_parent,
        )


class MountSet(tuple):
    """Simple, set-like class to hold mounts.

    It makes sure a mount is only present once. If a mount is marked as read only,
    but the same mount is added as writable the mount will be marked as writable.

    Inherits from tuple to be able to be used as a mount argument in docker.
    """

    @staticmethod
    def _mirror_readonly(x):
        x = x.copy()
        x["ReadOnly"] = not x["ReadOnly"]
        return x

    def __init__(self, iterable=()):
        self.data = []
        for o in iterable:
            self.add(o)

    def __contains__(self, value):
        return value in self.data or self._mirror_readonly(value) in self.data

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)

    def __repr__(self):
        return repr(self.data)

    def add(self, item):
        assert isinstance(
            item, Mount
        ), "Mount list can only hold docker.types.Mount objects."
        if item not in self.data:
            rev_item = self._mirror_readonly(item)
            if rev_item in self.data:
                self.data[self.data.index(rev_item)]["ReadOnly"] = False
            else:
                self.data.append(item)

    def discard(self, item):
        try:
            self.data.remove(item)
        except ValueError:
            try:
                self.data.remove(self._mirror_readonly(item))
            except ValueError:
                pass

    def remove(self, item):
        try:
            self.data.remove(item)
        except ValueError:
            try:
                self.data.remove(self._mirror_readonly(item))
            except ValueError:
                raise KeyError("Item not in MountSet")

    def update(self, iterable):
        for o in iterable:
            self.add(o)

    def count(self, value):
        return int(value in self)

    def index(self, value):
        try:
            return self.data.index(value)
        except ValueError:
            return self.data.index(self._mirror_readonly(value))
