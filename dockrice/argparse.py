from .dockerpath import DockerPath, DockerPathFactory
import argparse
import pathlib
import docker
import sys
from .utils import get_image


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
        script_name=None,
        container_name=None,
        run_command=["python"],
        user_callback=None,
        docker_kwargs=None,
    ):
        self.mounts = []
        self.run_command = []
        self.container_name = container_name
        self.docker_kwargs = docker_kwargs if docker_kwargs is not None else {}

        self._user_callback = user_callback

        if run_command is not None:
            self.run_command.extend(run_command)

        if script_name is not None:
            if not isinstance(script_name, DockerPath):
                script_name = DockerPath(script_name, mount_parent=True, read_only=True)
            self.mounts.append(script_name.get_mount())
            self.run_command.append(str(script_name.mount_path))

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
                self._docker_path_factory = DockerPathFactory(
                    mount_parent=kwargs.pop("mount_parent", None),
                    mount_path=kwargs.pop("mount_path", None),
                    read_only=kwargs.pop("read_only", False),
                )
                super().__init__(*args, **kwargs)

            def __call__(self, parser, namespace, values, option_string=None):
                # this is only called if the option_string was present in args
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
                if isinstance(ret_value, pathlib.PurePath) and not isinstance(
                    ret_value, DockerPath
                ):
                    ret_value = self._docker_path_factory(ret_value)
                if isinstance(ret_value, DockerPath):
                    self.run_command.append(str(ret_value.mount_path))
                    self.mounts.append(ret_value.get_mount())
                else:
                    self.run_command.append(parse_value)
                return ret_value

        return DockerAction

    def run_docker(self, args=None, unknown_args=None):
        if self._user_callback is not None:
            self._user_callback(self, args=args, unknown_args=unknown_args)

        if self.container_name is None:
            raise ValueError(
                "'container_name' is not defined. "
                "This is required for a docker to run"
            )

        # create docker client
        client = docker.from_env()

        # download image if not already present
        image = get_image(self.container_name, client)

        # run the docker container
        container = client.containers.run(
            image,
            self.run_command,
            detach=True,
            mounts=self.mounts,
            **self.docker_kwargs,
        )
        for line in container.logs(stream=True):
            print(line.decode("utf-8").strip())

        sys.exit(container.wait()["StatusCode"])


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        self._docker_action_factory = DockerActionFactory(
            script_name=kwargs.pop("script_name", None),
            container_name=kwargs.pop("container_name", None),
            run_command=kwargs.pop("run_command", ["python"]),
            user_callback=kwargs.pop("user_callback", None),
            docker_kwargs=kwargs.pop("docker_kwargs", None),
        )
        super().__init__(*args, **kwargs)

    def add_argument(self, *args, **kwargs):
        kwargs["action"] = self._docker_action_factory(
            action=kwargs.pop("action", None)
        )
        super().add_argument(*args, **kwargs)

    def parse_args(self, *args, **kwargs):
        args = super().parse_args(*args, **kwargs)
        self._docker_action_factory.run_docker(args=args)
        return args

    def parse_known_args(self, *args, **kwargs):
        args, unknown_args = super().parse_known_args(*args, **kwargs)
        self._docker_action_factory.run_docker(args=args, unknown_args=unknown_args)
        return args, unknown_args
