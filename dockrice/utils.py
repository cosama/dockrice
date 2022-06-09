import docker
import getpass
import signal
import os


def get_image(
    image_name: str,
    client: docker.DockerClient,
    try_pull: bool = True,
    try_login: bool = True,
):
    """Try to get an image, if it is not present try to pull it, if that
    doesn't work either try to login and pull again.

    Parameters
    ----------
    image_name : str
        The name of the docker image (including registry prefix if not dockerhub.com)
    client : docker.DockerClient
        The client instant to use

    try_pull : bool, optional
        If image is not available locally, try to pull it from the registry,
        by default True
    try_login : bool, optional
        If pulling from registry fails, try to login and pull again.

    Note: The login method is safe and doesn't store the password locally. If the
    password is in the local docker config files, it will use those.

    Returns
    -------
    docker.Image:
        The requested image
    """

    # TODO: We could try to use tqdm for pull status
    try:
        return client.images.get(image_name)
    except docker.errors.ImageNotFound as e:
        if not try_pull:
            raise e
        try:
            print(
                f"Trying to pull '{image_name}' from registry. Ths can take "
                "a while, please be patient..."
            )
            return client.images.pull(image_name)
        except docker.errors.APIError as e:
            if not try_login:
                raise e
            kwargs = {}
            if "/" in image_name:
                registry = image_name.split("/")[0]
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
                return client.images.pull(image_name)


class KillContainerOnInterrupt:
    """
    A context handler that always runs the given function on interrupt.
    """

    CATCHABLE_SIGNALS = set(signal.Signals) - {signal.SIGKILL, signal.SIGSTOP}

    def __init__(self, image, cmd, client=None, **kwargs):
        """
        Replaces default signal handlers with _handler, so that it doesn't
        immediately kill the program.
        """
        self.container = None
        self.image = image
        self.cmd = cmd
        self.kwargs = kwargs
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
        self.container = self.client.containers.run(
            self.image,
            self.cmd,
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


def run_image(image, cmd, client=None, **kwargs):
    """Run an image. Make sure it will be killed on signal interrupt.

    Parameters
    ----------
    image : docker.type.Image or str
        The image to run
    cmd : list or str
        The command to run in the docker
    client : docker.Client, optional
        The client to use for docker, by default None (create one)

    Returns:
    --------
    The containers exit code
    """
    with KillContainerOnInterrupt(image, cmd, client=None, **kwargs) as container:
        for line in container.logs(stream=True):
            print(line.decode("utf-8").strip())
        return container.wait()["StatusCode"]
