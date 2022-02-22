import argparse
import pathlib
import os
import sys

check_name = "AM_I_IN_A_DOCKER"

parser_arguments = [
    dict(
        option_strings="--bool-flag",
        help="A boolean flag.",
        default=False,
        action="store_true"
    ),
    dict(
        option_strings="--int-flag",
        help="A integer.",
        default=None,
        type=int
    ),
    dict(
        option_strings="output_files",
        help="A file to read data from",
        type=pathlib.Path,
        nargs="+"
    ),
]

if os.getenv(check_name, None) is None:
    from dockrice import run_in_docker
    rec = run_in_docker(
        docker_image="python",
        scriptname=__file__,
        args_list=parser_arguments,
        environment={check_name: ""})
    print(rec.decode("ASCII"))
    sys.exit()

parser = argparse.ArgumentParser(
    description="A simple example of running a script in docker."
)
for argument in parser_arguments:
    option_string = argument.pop("option_strings")
    parser.add_argument(option_string, **argument)

args = parser.parse_args()

for fname in args.output_files:
    with open(fname, "w") as ofile:
        ofile.write(sys.version)
        ofile.write(f"\nint-flag: {str(args.int_flag)}\nbool-flag: {str(args.bool_flag)}\n")

print("Writing done")
