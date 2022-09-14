# Dock-R-Ice: Get it? Run python scripts in docker from within python!

## Installation

```bash
pip3 install .
```
or for editable:

```bash
pip3 install --prefix=$(python3 -m site --user-base) --editable .
```

## How to use it

### Run a python script in a docker

The easiest way to use this library is to use the `dockrice.argparse.ArgumentParser` instant in your python script:


```
import os

check_name = "AM_I_IN_A_DOCKER"

if os.getenv(check_name, None) is None:
    import dockrice.argparse as argparse

    parser_kwargs = {
        "script_name": __file__,
        "container_name": "python",
        "docker_kwargs": {"environment": {check_name: ""}},
    }
else:
    import argparse

    parser_kwargs = {}

parser = argparse.ArgumentParser(
    description="A simple example of running a script in docker.", **parser_kwargs
)

# add more arguments here, use pathlib.Path for any file/directory

args = parser.parse_args()

# add additional imports and code here
```

This works because when the module is loaded, the environmental variable `AM_I_IN_A_DOCKER` is not defined. Thus, it uses the argparser from dockrice, with the respective parameters defined. For any file/directory that you use in your script you need an argument in the argparser with `type=pathlib.Path`. The argparser then starts a image, mounts all necessary path and runs the script in the container. The `AM_I_IN_A_DOCKER` variable is defined inside the container as it was added to the environmental variables passed to the docker run command, so it uses the normal `argparse` module and thus will run the full code without any special consideration.

The above code is thus about equivalent to

```
docker run -v $LOCAL_DATA_DIR:/data my_container python my_script.py --data-dir /data
```

but you only have to type 

```
python my_script.py --data-dir $LOCAL_DATA_DIR
```

and dockrice takes care of the rest for you.

### Support for scripting

The libary also offers a class `DockerPath`. It inherits from `pathlib.Path`, and can be used like any `pathlib.Path` object. However, it additionally also keeps track of the path a file or directory will be mounted inside a docker. This can be accessed with the `mount_path` method or you can get a `docker.types.Mount` object that can be used to correctly mount the file through the `get_mount` method. The `mount_path` is a `pathlib.PurePosixPath`, thus always represents the path of a linux file, while the `DockerPath` supports both windows and linux path syntax.

