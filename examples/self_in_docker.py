import pathlib
import os
import sys

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
parser.add_argument("--bool-flag", help="A boolean flag.", action="store_true")
parser.add_argument("--int-flag", help="A integer.", default=None, type=int),
parser.add_argument(
    "output_files",
    help="A bunch of files to write data to",
    type=pathlib.Path,
    nargs="+",
)

args = parser.parse_args()

for fname in args.output_files:
    with open(fname, "w") as ofile:
        ofile.write(sys.version)
        ofile.write(
            f"\nint-flag: {str(args.int_flag)}\nbool-flag: {str(args.bool_flag)}\n"
        )

print("Writing done")
