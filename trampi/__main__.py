#!/usr/bin/env python3

"""
Generate mpi_proxy.c from an MPI header.
"""

import argparse
import os
import shutil
import stat
import subprocess
import sys


from pathlib import Path
from .mpi_parser import parse_header, parse_header_patch
from .verify import verify
from .emitter import emit_proxy
from .verify_output import verify_output


def verify_header_patch(filename):
    """
    Verify that filename is a unified diff affecting only mpi.h.
    """

    filename = Path(filename)

    if not filename.is_file():
        raise RuntimeError(f"Patch file not found: {filename}")

    old = None
    new = None

    with filename.open(encoding="utf8") as f:

        for line in f:

            if line.startswith("--- "):
                old = line[4:].strip()

            elif line.startswith("+++ "):
                new = line[4:].strip()

    if old is None or new is None:
        raise RuntimeError("Not a unified diff.")

    def basename(path):
        path = path.split("\t", 1)[0]
        return Path(path).name

    if basename(old) != "mpi.h" or basename(new) != "mpi.h":
        raise RuntimeError("Header patch must modify only mpi.h.")


def apply_header_patch(header, header_patch, output_header):
    """Copy `header` to `output_header` and apply `header_patch` to it."""

    if shutil.which("patch") is None:
        raise RuntimeError(
            "The 'patch' command was not found. Please install it and ensure it is available on your PATH."
        )

    output_header = Path(output_header)
    output_header.parent.mkdir(parents=True, exist_ok=True)

    # Copy the original header.
    shutil.copy2(header, output_header)

    # Ensure the copied file is writable.
    mode = output_header.stat().st_mode
    os.chmod(output_header, mode | stat.S_IWUSR)

    # Apply the patch in-place.
    subprocess.run(
        [
            "patch",
            str(output_header),
            str(header_patch),
        ],
        check=True,
    )


def main():

    parser = argparse.ArgumentParser(description="Generate an MPI ABI trampoline.")

    parser.add_argument(
        "--header",
        required=True,
        help="Path to mpi.h",
    )

    parser.add_argument(
        "--header-patch",
        required=False,
        help="Path to patch for mpi.h which _only_ adds additional decalarations (e.g, for Fortran)",
    )

    parser.add_argument(
        "--stubs",
        required=True,
        help="Path to mpilib.c",
    )

    parser.add_argument(
        "-o",
        "--output",
        default="mpi_proxy.c",
        help="Output C file",
    )

    parser.add_argument(
        "--no-verify-output",
        action="store_true",
        help="Skip verification of generated output",
    )

    args = parser.parse_args()

    print(f"Reading {args.header}")
    functions = parse_header(args.header)

    extension_functions = []
    patch_text = ""
    if args.header_patch:
        verify_header_patch(args.header_patch)
        print(f"Reading {args.header_patch}")
        extension_functions = parse_header_patch(args.header_patch)

        # Place the patched mpi.h alongside the generated mpi_proxy.c
        output_dir = Path(args.output).resolve().parent
        patched_header_path = output_dir / "mpi.h"
        apply_header_patch(
            args.header,
            args.header_patch,
            patched_header_path,
        )
        patch_text = f" and {patched_header_path}"

    # Remove duplicates, last declaration wins (shouldn't happen but still...)
    all_functions = {function.name: function for function in functions}
    # extension_functions may replace a function (case in point MPI_Precv_init/MPI_Psend_init)
    all_functions.update({function.name: function for function in extension_functions})
    if patch_text:
        # Drop (P)MPI_Precv_init_c/(P)MPI_Psend_init_c completely
        # (if that is wrong it will pop up in verification)
        all_functions.pop("MPI_Precv_init_c", None)
        all_functions.pop("MPI_Psend_init_c", None)
        all_functions.pop("PMPI_Precv_init_c", None)
        all_functions.pop("PMPI_Psend_init_c", None)

    all_functions = list(all_functions.values())
    verify(all_functions)

    print(f"Reading {args.stubs}")

    emit_proxy(
        functions=functions,
        extension_functions=extension_functions,
        mpi_stubs=args.stubs,
        output=args.output,
    )

    print(f"Wrote {args.output}")

    if not args.no_verify_output:
        verify_output(
            functions=functions,
            extension_functions=extension_functions,
            mpi_stubs=args.stubs,
            mpi_proxy=args.output,
        )

    print(f"{Path(args.output).resolve()}{patch_text} have been written.")
    print("Done.")


if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        sys.exit(1)

    except Exception as e:

        print()

        print("ERROR")

        print(e)

        sys.exit(1)
