# Copyright (C) 2021 Marco Salathe (www.github.com/cosama/)

import pathlib
import uuid
from docker.types import Mount
from typing import Union, Tuple
from enum import Enum

PathLike = Union[pathlib.PurePath, str]


class DefaultMountOption(Enum):
    random = 0
    host = 1


class DockerPath(type(pathlib.Path())):

    default_mount = DefaultMountOption.random

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
        mount_path: PathLike = None,
        read_only: bool = False,
        mount_parent: Union[bool, None] = None,
    ) -> None:
        """Create a DockerPath object.

        Parameters
        ----------
        path: PathLike (identical to pathlib.Path creator)
            The host path.
        mount_path : PathLike, optional
            The path inside the docker container, by default None, e.g.
            created by a uuid + path.suffix. CAUTION: If 'mount_parent' is true,
            this will be the parent path and path.name will be appended, otherwise
            this will be the full path.
        read_only : bool, optional
            Mount the path with read only access, by default False.
        mount_parent : Union[bool, None], optional
            Do not mount path itself, but it's parent instead, by default None.
            If None, will check if the path exist, if it does, this is set to False,
            if not it is set to True.
        """
        self.mount_path = mount_path
        if mount_parent is None:
            if self.exists():
                mount_parent = False
            else:
                mount_parent = True
        self.mount_parent = mount_parent
        self.read_only = read_only

    @property
    def read_only(self) -> bool:
        return self._read_only

    @read_only.setter
    def read_only(self, value: bool):
        assert value in (False, True), "read_only needs to be a boolean"
        self._read_only = value

    @property
    def mount_parent(self) -> bool:
        return self._mount_parent

    @mount_parent.setter
    def mount_parent(self, value: bool):
        assert value in (
            False,
            True,
            None,
        ), "mount_parent needs to be a boolean or None"
        self._mount_parent = value

    @property
    def mount_path(self: PathLike) -> pathlib.PurePath:
        if self._mount_path is None:
            if DockerPath.default_mount == DefaultMountOption.random:
                if self.mount_parent:
                    return pathlib.PosixPath(
                        "/temp", self._default_mount_uuid, self.name
                    )
                return pathlib.PosixPath(
                    "/temp", self._default_mount_uuid + self.suffix
                )
            if DockerPath.default_mount == DefaultMountOption.host:
                return pathlib.PosixPath(self.resolve(strict=False))
        if self.mount_parent:
            return pathlib.PosixPath(self._mount_path, self.name)
        return self._mount_path

    @mount_path.setter
    def mount_path(self, path: PathLike):
        self._default_mount_uuid = str(uuid.uuid4())
        if path is not None:
            if isinstance(path, tuple):
                path = pathlib.PosixPath(*path)
            else:
                path = pathlib.PosixPath(path)
            assert path.is_absolute(), "Require an absolute path for the mount path"
        self._mount_path = path

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
        mount_path: PathLike = None,
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
