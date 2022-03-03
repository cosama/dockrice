import argparse
import pathlib
import os
import sys

check_name = "AM_I_IN_A_DOCKER"


parser = argparse.ArgumentParser(
    description="A simple example of running a script in docker."
)

if os.getenv(check_name, None) is None:
    from dockrice import DockerActionFactory

    action_factory = DockerActionFactory(scriptname=__file__)
else:

    def action_factory(action):
        return action


parser.add_argument(
    "--bool-flag", help="A boolean flag.", action=action_factory("store_true")
)
parser.add_argument(
    "--int-flag", help="A integer.", default=None, type=int, action=action_factory(None)
),
parser.add_argument(
    "output_files",
    help="A bunch of files to write data to",
    type=pathlib.Path,
    nargs="+",
    action=action_factory(None),
)

args = parser.parse_args()

if os.getenv(check_name, None) is None:
    import docker

    # run the docker container
    client = docker.from_env()
    container = client.containers.run(
        "python",
        action_factory.run_command,
        environment={check_name: ""},
        detach=True,
        mounts=action_factory.mounts,
    )
    for line in container.logs(stream=True):
        print(line.decode("ASCII").strip())
    sys.exit()


for fname in args.output_files:
    with open(fname, "w") as ofile:
        ofile.write(sys.version)
        ofile.write(
            f"\nint-flag: {str(args.int_flag)}\nbool-flag: {str(args.bool_flag)}\n"
        )

print("Writing done")
