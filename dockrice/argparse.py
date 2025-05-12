import argparse
import sys
import pathlib
import docker
from .dockerpath import DockerPath, DockerPathFactory, MountOption, MountSet
from .utils import get_image, run_image, resolve_gpu_device
import warnings
import inspect


class DockerizeDoneExit(SystemExit):
    pass


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

    def __init__(
        self,
        image=None,
        run_command=["python"],
        script_name=None,
        user_callback=None,
        docker_kwargs=None,
        dockrice_verbose=False,
        mounts=None,
    ):
        if mounts is None:
            self.mounts = MountSet()
        else:
            self.mounts = MountSet(
                [
                    (
                        m.get_mount()
                        if isinstance(m, DockerPath)
                        else DockerPath(m).get_mount()
                    )
                    for m in mounts
                ]
            )
        self.run_command = []
        self.default_mounts = []
        self.image = image

        self.docker_kwargs = docker_kwargs if docker_kwargs is not None else {}
        # set working_dir to current directory, so that relative path work
        self.docker_kwargs.setdefault("working_dir", str(pathlib.Path.cwd()))

        self.dockrice_verbose = dockrice_verbose

        self._user_callback = user_callback

        if run_command is not None:
            self.run_command.extend(run_command)

        if script_name is None:
            frame = sys._getframe(2)
            if frame is None:
                raise NotImplementedError(
                    "Can not evaluate 'script_name' automatically. "
                    "Please provide the argument."
                )
            script_name = frame.f_globals["__file__"]

        if script_name != "":
            if not isinstance(script_name, DockerPath):
                script_name = DockerPath(script_name, mount_parent=True, read_only=True)
            self.mounts.add(script_name.get_mount())
            self.run_command.append(str(script_name.mount_path))

    def __call__(factory_self, action=None):

        if action is None:
            action = "store"
        if isinstance(action, str):
            action = getattr(argparse, factory_self.select[action])

        class DockerAction(action):
            mounts = factory_self.mounts
            default_mounts = factory_self.default_mounts
            run_command = factory_self.run_command
            default_mounts = factory_self.default_mounts

            def __init__(self, *args, **kwargs):
                # if type is Path and default is defined, we need to mount it
                # the default will be replaced.
                self._default_mount = None
                type_value = kwargs.get("type", type(None))
                if (
                    "default" in kwargs
                    and inspect.isclass(type_value)  # it could be an object
                    and issubclass(type_value, pathlib.PurePath)
                ):
                    if kwargs["default"] is not None:
                        if isinstance(kwargs["default"], DockerPath):
                            self._default_mount = kwargs["default"].get_mount()
                        else:
                            self._default_mount = DockerPath(
                                kwargs["default"],
                                mount_parent=kwargs.get("mount_parent", None),
                                mount_path=kwargs.get("mount_path", MountOption.host),
                                read_only=kwargs.get("read_only", False),
                            ).get_mount()
                        self.default_mounts.append(self._default_mount)

                # here we postpone the type conversion and choice checking
                self._hidden_type = kwargs.pop("type", None)
                self._hidden_choices = kwargs.pop("choices", None)
                self._docker_path_factory = DockerPathFactory(
                    mount_parent=kwargs.pop("mount_parent", None),
                    mount_path=kwargs.pop("mount_path", MountOption.host),
                    read_only=kwargs.pop("read_only", False),
                )
                super().__init__(*args, **kwargs)

            def __call__(self, parser, namespace, values, option_string=None):
                # remove default, now that we call the action
                if self._default_mount is not None:
                    self.default_mounts.remove(self._default_mount)
                # this is only called if the option_string was present in args
                if option_string == "--dockrice-verbose":
                    factory_self.dockrice_verbose = True
                    delattr(namespace, "dockrice_verbose")
                    return
                if option_string == "--gpus":
                    factory_self.docker_kwargs.setdefault("device_requests", [])
                    factory_self.docker_kwargs["device_requests"].extend(
                        resolve_gpu_device(values)
                    )
                    delattr(namespace, "gpus")
                    return
                if option_string is not None:
                    self.run_command.append(option_string)
                values = self._recursive_resolve_args(values)
                super().__call__(parser, namespace, values, option_string=option_string)

            def _recursive_resolve_args(self, parse_value):
                if isinstance(parse_value, list):
                    ret_value = []
                    for v in parse_value:
                        ret_value.append(self._recursive_resolve_args(v))
                    return ret_value
                # here we do the type conversion and choice checking
                if self._hidden_type is not None:
                    ret_value = self._hidden_type(parse_value)
                else:
                    ret_value = parse_value
                if (
                    self._hidden_choices is not None
                    and ret_value not in self._hidden_choices
                ):
                    raise argparse.ArgumentError(
                        self,
                        f"invalid choice: {ret_value} (choose from {self._hidden_choices})",
                    )
                # here we convert any Path like object to a DockerPath
                if isinstance(ret_value, pathlib.PurePath) and not isinstance(
                    ret_value, DockerPath
                ):
                    ret_value = self._docker_path_factory(ret_value)
                if isinstance(ret_value, DockerPath):
                    self.run_command.append(str(ret_value.mount_path))
                    self.mounts.add(ret_value.get_mount())
                else:
                    self.run_command.append(parse_value)
                return ret_value

        return DockerAction

    def run_docker(self, args=None, unknown_args=None):
        if self._user_callback is not None:
            self._user_callback(self, args=args, unknown_args=unknown_args)

        if self.image is None:
            raise ValueError(
                "'image' is not defined. This is required for a docker to run."
            )

        # create docker client
        client = docker.from_env()

        # download image if not already present
        image = get_image(self.image, client, dockrice_verbose=self.dockrice_verbose)

        # run the docker container
        return run_image(
            image,
            self.run_command,
            client=client,
            mounts=MountSet([*self.mounts, *self.default_mounts]),
            **self.docker_kwargs,
            dockrice_verbose=self.dockrice_verbose,
        )


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        if "container_name" in kwargs:
            assert "image" not in kwargs, "Use either 'image' or 'container_name'."
            warnings.warn("'container_name' is deprecated, please use 'image'.")
            kwargs["image"] = kwargs.pop("container_name")

        self._docker_action_factory = DockerActionFactory(
            script_name=kwargs.pop("script_name", None),
            image=kwargs.pop("image", None),
            run_command=kwargs.pop("run_command", ["python"]),
            user_callback=kwargs.pop("user_callback", None),
            docker_kwargs=kwargs.pop("docker_kwargs", None),
            mounts=kwargs.pop("mounts", None),
        )
        self._raise_on_unknown = False
        super().__init__(*args, **kwargs)
        self.add_argument(
            "--dockrice-verbose",
            help="Increases verbosity of dockrice.",
            action="store_true",
        )
        self.add_argument(
            "--gpus",
            help="Adds gpu capability to the docker container.",
            type=str,
        )

    def add_argument(self, *args, **kwargs):
        kwargs["action"] = self._docker_action_factory(
            action=kwargs.pop("action", None)
        )
        super().add_argument(*args, **kwargs)

    # Wo only overwrite parse_known_args parse_args is calling
    # parse_known args internally
    def parse_known_args(self, *args, **kwargs):
        args, unknown_args = super().parse_known_args(*args, **kwargs)
        if self._docker_action_factory.dockrice_verbose:
            print("Dockrice ArgumentParser:")
            print(f"    Parsed args: {args}")
            print(f"    Unknown args: {unknown_args}")
        if self._raise_on_unknown and unknown_args:
            msg = "unrecognized arguments: %s"
            self.error(msg % " ".join(unknown_args))
        self._raise_on_unknown = False
        ret_value = self._docker_action_factory.run_docker(
            args=args, unknown_args=unknown_args
        )
        raise DockerizeDoneExit(ret_value)

    def parse_args(self, args=None, namespace=None):
        self._raise_on_unknown = True
        self.parse_known_args(args=args, namespace=namespace)
