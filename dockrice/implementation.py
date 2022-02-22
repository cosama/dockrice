import pathlib
import uuid
from docker.types import Mount
import docker
import argparse
from typing import Union, List, Tuple, Dict


PathLike = Union[pathlib.PurePath, str]


class DockerPath():
    def __init__(
        self, path: PathLike,
        mount_path: PathLike=None,
        read_only: bool=False,
        mount_parent: Union[bool, None]=None
    ) -> None:
        self.path = path
        self.mount_path = mount_path
        if mount_parent is None:
            if self.path.exists():
                mount_parent = False
            else:
                if self.path.parent.exists():
                    mount_parent = True
                else:
                    ValueError(f"Neither {str(self.path)} nor it's parent exist.")
        self._mount_parent = mount_parent
        self._read_only = read_only


    @property
    def path(self) -> pathlib.PurePath:
        return self._path

    @path.setter
    def path(self, path: PathLike):
        self._path = pathlib.Path(path)

    @property
    def mount_path(self: PathLike) -> pathlib.PurePath:
        if self._mount_parent:
            return pathlib.PosixPath(self._mount_path, self.path.name)
        return self._mount_path

    @property
    def name(self) -> pathlib.PurePath:
        return self.path.name

    @property
    def parent(self) -> pathlib.PurePath:
        return self.path.parent

    def __fspath__(self) -> str:
        return str(self.path)

    @mount_path.setter
    def mount_path(self, path: PathLike)-> pathlib.PurePath:
        if path is None:
            path = pathlib.PosixPath("/temp", str(uuid.uuid4()))
        else:
            path = pathlib.PosixPath(path)
        assert path.is_absolute(), "Require an absolute path for the mount path"
        self._mount_path = path

    def _get_target_source(self) -> Tuple[pathlib.PurePath]:
        if self._mount_parent:
            target = self.mount_path.parent
            source = self.path.parent
        else:
            target = self.mount_path
            source = self.path
        return target, source

    def get_mount(self) -> Mount:
        target, source = self._get_target_source()
        return Mount(
            str(target),
            str(source.resolve()),
            type='bind',
            read_only=self._read_only,
        )

    def get_mount_string(self) -> List[str]:
        target, source = self._get_target_source()
        access_rights= 'ro' if self.read_only else 'rw'
        return f"{str(source.resolve())}:{str(target)}:{access_rights}"


class DockerActionFactory:

    select = {
        'store': "_StoreAction",
        'store_const': "_StoreConstAction",
        'store_true': "_StoreTrueAction",
        'store_false': "_StoreFalseAction",
        'append': "_AppendAction",
        'append_const': "_AppendConstAction",
        'count': "_CountAction",
        'help': "_HelpAction",
        'version': "_VersionAction",
        'parsers': "_SubParsersAction",
        'extend': "_ExtendAction",
    }

    def __init__(self):
        self.mounts = []
        self.run_command = []

    def new_action(self, action='store'):

        if isinstance(action, str):
            action = getattr(argparse, self.select[action])

        class DockerAction(action):
            mounts = self.mounts
            run_command = self.run_command

            def _recursive_resolve_args(self, parse_value, option_string=None):
                if option_string is not None:
                    self.run_command.append(option_string)
                if isinstance(parse_value, (list, tuple)):
                    ret_value = parse_value.__class__()
                    for v in parse_value:
                        ret_value.append(self._recursive_resolve_args(v))
                    return ret_value
                if isinstance(parse_value, (pathlib.PurePath, DockerPath)):
                    if isinstance(parse_value, pathlib.PurePath):
                        ret_value = DockerPath(parse_value)
                    else:
                        ret_value = parse_value
                    self.run_command.append(str(parse_value.mount_path))
                    self.mounts.append(parse_value.get_mount())
                else:
                    self.run_command.append(str(parse_value))
                    ret_value = parse_value
                return ret_value

            def __call__(self, parser, namespace, values, option_string=None):
                values = self._recursive_resolve_args(values, option_string=option_string)
                super().__call__(parser, namespace, values, option_string=option_string)

        return DockerAction


def run_in_docker(
    docker_image: str,
    scriptname: Union[PathLike, DockerPath],
    args_list: List[Dict],
    prefix: Union[str, None]="python",
    **kwargs
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
        if "type" in argument and issubclass(argument["type"], (pathlib.PurePath, DockerPath)):
            argument_kwargs["type"] = DockerPath
        if "nargs" in argument:
            argument_kwargs["nargs"] = argument["nargs"]

        parser.add_argument(*option_strings, **argument_kwargs)

    # run the parser and populate the action factory
    _, unknown_args = parser.parse_known_args()

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