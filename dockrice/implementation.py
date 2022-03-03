# Copyright (C) 2021 Marco Salathe (www.github.com/cosama/)

import pathlib
import uuid
from docker.types import Mount
import docker
import argparse
from typing import Union, List, Tuple, Dict, Any


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


# This works because the order argparse performs tasks is as follows:
#    1) Apply type (grab definition from Action.type)
#    2) Check choices (grab definition from Action.choices)
#    3) call action (__call__)
#    4) add default for those not in namespace
# The goal of this is to not do the first two, by removing the type and choices
# in the action __init__ method, but then perfrom them manually in the the
# action call method, when recursively parsing all provided values. So the final
# namespace will be identical to the one argparse would be creating, but we have
# access to the proper option strings and unaltered arguments in __call__.
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

    def __call__(factory_self, action=None):

        if action == None:
            action = "store"
        if isinstance(action, str):
            action = getattr(argparse, factory_self.select[action])

        class DockerAction(action):
            mounts = factory_self.mounts
            run_command = factory_self.run_command

            def __init__(self, *args, **kwargs):
                # here we postpone the type conversion and choice checking
                self._hidden_type = kwargs.pop("type", None)
                self._hidden_choices = kwargs.pop("choices", None)
                super().__init__(*args, **kwargs)

            def __call__(self, parser, namespace, values, option_string=None):
                # this is only called if the option_string was present in args
                if option_string is not None:
                    self.run_command.append(option_string)
                values = self._recursive_resolve_args(
                    values, option_string=option_string
                )
                super().__call__(parser, namespace, values, option_string=option_string)

            def _recursive_resolve_args(self, parse_value, option_string=None):
                if isinstance(parse_value, list):
                    ret_value = []
                    for v in parse_value:
                        ret_value.append(
                            self._recursive_resolve_args(v, option_string=option_string)
                        )
                    return ret_value
                # here we do the type conversion and choice checking
                ret_value = self._hidden_type(parse_value)
                if (
                    self._hidden_choices is not None
                    and ret_value not in self._hidden_choices
                ):
                    raise argparse.ArgumentError(
                        self,
                        f"invalid choice: {ret_value} (choose from {self._hidden_choices})",
                    )
                # here we convert any Path like object to a DockerPath
                if isinstance(ret_value, pathlib.PurePath) and not isinstance(ret_value, DockerPath):
                    ret_value = DockerPath(ret_value)
                if isinstance(ret_value, DockerPath):
                    self.run_command.append(str(ret_value.mount_path))
                    self.mounts.append(ret_value.get_mount())
                else:
                    self.run_command.append(parse_value)
                return ret_value

        return DockerAction


def parse_docker_args(
    scriptname: Union[PathLike, DockerPath],
    args_list: List[Dict[str, Any]],
    prefix: Union[str, None] = "python",
    namespace: argparse.Namespace = None,
    args: List[str] = None,
    **kwargs,
) -> Tuple[List[str], List[docker.types.Mount]]:
    """parse arguments to populate a run command and a docker Mount list.

    Parameters
    ----------
    scriptname : Union[PathLike, DockerPath]
        The name of the script to be run inside a docker
    args_list : List[Dict[str, Any]]
        A list of arguments to populate an argument parser. Requires
        an 'option_strings' entry and can use additional to the normal kwargs
        these options: 'mount_parent', 'read_only', 'mount_path'.
    prefix : Union[str, None], optional
        A prefix, defining how the script needs to be called, by default "python"
    namespace : argparse.Namespace, optional
        If provided the internal argument parser will populate this, by default None
    args : List[str], optional
        A list of arguments to parse, by default None (sys.argv will be used)
    kwargs : keyword argumentds
        Will be passed along to the internal ArgumentParser.

    Returns
    -------
    Tuple[List[str], List[docker.types.Mount]]
        The command that needs to be run in a docker and the mounts that need to be,
        mounted for the command to executed correctly in the docker.
    """

    # create an action factory, this is used to collect the docker args
    action_factory = DockerActionFactory()

    # check prefix
    if prefix is not None:
        action_factory.run_command.append(prefix)

    # prepare filename
    if not isinstance(scriptname, DockerPath):
        scriptname = DockerPath(scriptname, mount_parent=True, read_only=True)
    action_factory.mounts.append(scriptname.get_mount())
    action_factory.run_command.append(str(scriptname.mount_path))

    # create a minimal argument parser based on the action factory's action
    parser = argparse.ArgumentParser(**kwargs)
    for argument in args_list:
        # we need to remove option string and make sure it is a list
        option_strings = argument.pop("option_strings")
        if isinstance(option_strings, str):
            option_strings = [option_strings]
        # then we replace the action with the one from the action factory
        argument["action"] = action_factory(argument.pop("action", None))
        # and we add the arguments
        parser.add_argument(*option_strings, **argument)

    # run the parser and populate the action factory. FIXME: use parse_args?
    unknown_args = parser.parse_known_args(args=args, namespace=namespace)[1]

    # add unknown arguments, FIXME: is it okay to add them to the end?
    action_factory.run_command.extend(unknown_args)

    return action_factory.run_command, action_factory.mounts


def run_in_docker(
    docker_image: str,
    scriptname: Union[PathLike, DockerPath],
    args_list: List[Dict],
    prefix: Union[str, None] = "python",
    **kwargs,
):

    run_command, mounts = parse_docker_args(scriptname, args_list, prefix=prefix)

    # run the docker
    client = docker.from_env()
    return client.containers.run(
        docker_image,
        run_command,
        mounts=mounts,
        **kwargs,
    )
