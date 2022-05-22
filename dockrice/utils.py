import docker
import getpass


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
