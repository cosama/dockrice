import pathlib
import uuid
from docker.types import Mount
import docker
import argparse
from typing import Union, List, Tuple, Dict


PathLike = Union[pathlib.PurePath, str]


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
        assert value in (False, True), "mount_parent needs to be a boolean"
        self._mount_parent = value

    @property
    def mount_path(self: PathLike) -> pathlib.PurePath:
        if self._mount_parent:
            return pathlib.PosixPath(self._mount_path, self.name)
        return self._mount_path

    @mount_path.setter
    def mount_path(self, path: PathLike):
        if isinstance(path, tuple):
            path = pathlib.PosixPath(*path)
        elif path is None:
            path = pathlib.PosixPath("/temp", str(uuid.uuid4()) + self.suffix)
        else:
            path = pathlib.PosixPath(path)
        assert path.is_absolute(), "Require an absolute path for the mount path"
        self._mount_path = path

    def _get_target_source(self) -> Tuple[pathlib.PurePath]:
        if self._mount_parent:
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


class DockerActionFactory:

    select = {
        "store": "_StoreAction",
        "store_const": "_StoreConstAction",
        "store_true": "_StoreTrueAction",
        "store_false": "_StoreFalseAction",
        "append": "_AppendAction",
        "append_const": "_AppendConstAction",
        "count": "_CountAction",
        "help": "_HelpAction",
        "version": "_VersionAction",
        "parsers": "_SubParsersAction",
        "extend": "_ExtendAction",
    }

    def __init__(self):
        self.mounts = []
        self.run_command = []

    def _recursive_resolve_args(
        self,
        parse_value,
        option_string=None,
        mount_parent=None,
        read_only=False,
        mount_path=None,
    ):
        if option_string is not None:
            self.run_command.append(option_string)

        if isinstance(parse_value, (list, tuple)):
            ret_value = parse_value.__class__()
            for v in parse_value:
                ret_value.append(
                    self._recursive_resolve_args(
                        v,
                        mount_parent=mount_parent,
                        read_only=read_only,
                        mount_path=mount_path,
                    )
                )
            return ret_value

        if isinstance(parse_value, pathlib.PurePath):
            if not isinstance(parse_value, DockerPath):
                ret_value = DockerPath(
                    parse_value,
                    mount_parent=mount_parent,
                    read_only=read_only,
                    mount_path=mount_path,
                )
            else:
                ret_value = parse_value
            self.run_command.append(str(ret_value.mount_path))
            self.mounts.append(ret_value.get_mount())
        else:
            self.run_command.append(str(parse_value))
            ret_value = parse_value

        return ret_value

    def new_action(factory_self, action="store"):

        if isinstance(action, str):
            action = getattr(argparse, factory_self.select[action])

        class DockerAction(action):
            mounts = factory_self.mounts
            run_command = factory_self.run_command

            def __init__(self, *args, **kwargs):
                self.mount_parent = kwargs.pop("mount_parent", None)
                self.read_only = kwargs.pop("read_only", False)
                self.mount_path = kwargs.pop("mount_path", None)
                print(
                    f"Setting: {self.mount_parent}, {self.read_only}, {self.mount_path}"
                )
                super().__init__(*args, **kwargs)

            def __call__(self, parser, namespace, values, option_string=None):
                factory_self._recursive_resolve_args(
                    values,
                    option_string=option_string,
                    mount_parent=self.mount_parent,
                    read_only=self.read_only,
                    mount_path=self.mount_path,
                )
                super().__call__(parser, namespace, values, option_string=option_string)

        return DockerAction


def run_in_docker(
    docker_image: str,
    scriptname: Union[PathLike, DockerPath],
    args_list: List[Dict],
    prefix: Union[str, None] = "python",
    **kwargs,
):

    # create an action factory, this is used to collect the docker args
    action_factory = DockerActionFactory()
    # prepare initial mounts
    action_factory.mounts.extend(kwargs.pop("mounts", []))

    # check prefix
    if prefix is not None:
        action_factory.run_command.append(prefix)

    # prepare filename
    if not isinstance(scriptname, DockerPath):
        scriptname = DockerPath(scriptname, mount_parent=True, read_only=True)
    action_factory.mounts.append(scriptname.get_mount())
    action_factory.run_command.append(str(scriptname.mount_path))

    # create a minimal argument parser based on the action factory's action
    parser = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    for argument in args_list:
        if isinstance(argument["option_strings"], str):
            option_strings = [argument["option_strings"]]
        else:
            option_strings = argument["option_strings"]

        argument_kwargs = {}
        if "action" in argument:
            argument_kwargs["action"] = action_factory.new_action(argument["action"])
        else:
            argument_kwargs["action"] = action_factory.new_action()
        if "type" in argument and issubclass(
            argument["type"], (pathlib.PurePath, DockerPath)
        ):
            argument_kwargs["type"] = argument["type"]
        if "nargs" in argument:
            argument_kwargs["nargs"] = argument["nargs"]
        argument_kwargs["mount_parent"] = argument.pop("mount_parent", None)
        argument_kwargs["read_only"] = argument.pop("read_only", False)
        argument_kwargs["mount_path"] = argument.pop("mount_path", None)

        parser.add_argument(*option_strings, **argument_kwargs)

    # run the parser and populate the action factory
    unknown_args = parser.parse_known_args()[1]

    # add unknown arguments, FIXME: is it okay to add them to the end?
    action_factory.run_command.extend(unknown_args)

    # run the docker
    client = docker.from_env()
    return client.containers.run(
        docker_image,
        action_factory.run_command,
        mounts=action_factory.mounts,
        **kwargs,
    )
