import docker
import getpass
import signal
import os
from typing import Union


def get_image(
    image: Union[str, docker.models.images.Image],
    client: docker.DockerClient = None,
    try_pull: bool = True,
    try_login: bool = True,
    dockrice_verbose: bool = False,
):
    """Try to get an image, if it is not present try to pull it, if that
    doesn't work either try to login and pull again.

    Parameters
    ----------
    image : str or docker.models.images.Image
        The name of the docker image (including registry prefix if not dockerhub.com)
        or the image to be run.
    client : docker.DockerClient, optional
        The client instant to use
    try_pull : bool, optional
        If image is not available locally, try to pull it from the registry,
        by default True
    try_login : bool, optional
        If pulling from registry fails, try to login and pull again.
    dockrice_verbose : bool, optional
        Set increased verbosity

    Note: The login method is safe and doesn't store the password locally. If the
    password is in the local docker config files, it will use those.

    Returns
    -------
    docker.models.images.Image:
        The requested image
    """
    if isinstance(image, docker.models.images.Image):
        return image

    if client is None:
        # create docker client
        client = docker.from_env()

    # TODO: We could try to use tqdm for pull status
    try:
        return client.images.get(image)
    except docker.errors.ImageNotFound as e:
        if not try_pull:
            raise e
        try:
            print(
                f"Trying to pull '{image}' from registry. This can take "
                "a while, please be patient..."
            )
            return client.images.pull(image)
        except docker.errors.APIError as e:
            if not try_login:
                raise e
            kwargs = {}
            if "/" in image:
                registry = image.split("/")[0]
            else:
                registry = "Default"
            print(f"Can not access registry ({registry}). Try to login:")
            if registry != "Default":
                kwargs["registry"] = registry
            kwargs["username"] = str(input("Username: "))
            try:
                client.login(**kwargs)
            except docker.errors.APIError:
                kwargs["password"] = getpass.getpass()
                client.login(**kwargs)
                print("Login successful. Pulling the image...")
                return client.images.pull(image)


class KillContainerOnInterrupt:
    """
    A context handler that always runs the given function on interrupt.
    """

    # this will work on windows where other signals are available
    try:
        CATCHABLE_SIGNALS = set(signal.Signals) - {signal.SIGKILL, signal.SIGSTOP}
    except AttributeError:
        CATCHABLE_SIGNALS = set(signal.Signals) - {
            signal.CTRL_C_EVENT,
            signal.CTRL_BREAK_EVENT,
        }

    def __init__(
        self,
        image,
        cmd,
        client=None,
        auto_remove=True,
        dockrice_verbose=False,
        **kwargs,
    ):
        """
        Replaces default signal handlers with _handler, so that it doesn't
        immediately kill the program.
        """
        detach = kwargs.pop("detach", True)
        if detach is False:
            print(
                "WARNING: Requires container to be detached, 'detach' will be ignored."
            )
        self.container = None
        self.image = image
        self.cmd = cmd
        self.kwargs = kwargs
        self.dockrice_verbose = dockrice_verbose
        self.auto_remove = auto_remove
        if client is None:
            # create docker client
            client = docker.from_env()
        self.client = client
        self._old_handlers = {}

    def __enter__(self):
        """
        Replaces default signal handlers with _handler, so that it doesn't
        immediately kill the program.
        """

        for sig in self.CATCHABLE_SIGNALS:
            self._old_handlers[sig] = signal.signal(sig, self._handler)

        # run the docker container
        if self.dockrice_verbose is True:
            print("Running container:")
            print(f"    Image: {self.image}")
            print(f"    Command: {self.cmd}")
            print(f"    Kwargs: {self.kwargs}")
        self.container = self.client.containers.run(
            self.image,
            self.cmd,
            detach=True,
            **self.kwargs,
        )

        return self.container

    def _handler(self, sig, frame):
        """
        Function is the new default handler, it runs the given func and then
        calls the old signal handler.
        See: https://stackoverflow.com/questions/66699397/default-signal-handling-in-python?rq=1
        """
        if self.container is not None:
            self.container.kill(sig)
        old_handler = self._old_handlers[sig]
        if callable(old_handler):
            old_handler(sig, frame)
        elif old_handler == signal.SIG_DFL:
            signal.signal(sig, signal.SIG_DFL)
            os.kill(os.getpid(), sig)

    def __exit__(self, exc_type, exc_value, exc_traceback):
        """
        Function resets the signal handlers back to default.
        """
        for sig, old_handler in self._old_handlers.items():
            signal.signal(sig, old_handler)
        if self.auto_remove:
            if self.dockrice_verbose is True:
                print(f"Removing container: {self.container}.")
            self.container.remove(force=True)


def run_image(image, cmd, client=None, return_logs=False, auto_remove=True, **kwargs):
    """Run an image. Make sure it will be killed on signal interrupt.

    Parameters
    ----------
    image : docker.type.Image or str
        The image to run
    cmd : list or str
        The command to run in the docker
    client : docker.Client, optional
        The client to use for docker, by default None (create one)
    return_logs : bool, optional
        instead of writing to stdout return the log as second parameter
    auto_remove : bool, optional
        Automatically remove the container on exit. Is True by default


    Returns:
    --------
    The containers exit code, (the log as a list of strings)
    """
    with KillContainerOnInterrupt(
        image, cmd, client=client, auto_remove=auto_remove, **kwargs
    ) as container:
        if return_logs:
            ret_string = [line.decode("utf-8") for line in container.logs(stream=True)]
            return container.wait()["StatusCode"], ret_string

        for line in container.logs(stream=True):
            print(line.decode("utf-8"), end="", flush=True)
        return container.wait()["StatusCode"]


def resolve_gpu_device(arg):
    """Takes a string, similar to the docker --gpus flag and converts it to dockerpy.

    Parameters
    ----------
    args: str
        The string that would be passed to the --gpus flag: "all" or "device=...".

    Returns:
    --------
    a list of DeviceRequest objects
    """

    if arg == "all":
        return [docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])]
    elif arg.startswith("device="):
        devices = arg.replace("device=", "").split(",")
        return [docker.types.DeviceRequest(device_ids=devices, capabilities=[["gpu"]])]

    raise ValueError(f"Unknown gpu device value: {arg}")
