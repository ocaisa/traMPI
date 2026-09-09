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
import re


from pathlib import Path
from .mpi_parser import parse_header, parse_header_patch
from .emitter import emit_proxy


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

    # Ensure the original header is writable.
    orig_path = Path(header)
    mode = orig_path.stat().st_mode
    os.chmod(orig_path, mode | stat.S_IWUSR)

    # Apply the patch in-place to the original header.
    subprocess.run(
        [
            "patch",
            "-l",
            str(orig_path),
            str(header_patch),
        ],
        check=True,
    )

    # Copy the patched header to the destination.
    shutil.copy2(orig_path, output_header)


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
        "--stubs-extra",
        required=False,
        help="Path to additional C file(s) to concatenate with mpilib.c "
             "(e.g., f2c_abi_stubs.c). Required when --header-patch is used.",
    )

    parser.add_argument(
        "-o",
        "--output",
        default=".",
        help="Output directory for mpi_proxy.c (and mpi.h when using --header-patch)",
    )

    args = parser.parse_args()

    output_dir = Path(args.output).resolve()

    if output_dir.exists() and not output_dir.is_dir():
        print(f"ERROR: --output must be a directory, got file: {args.output}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "mpi_proxy.c"

    # Validate: header-patch and stubs-extra must be used together
    mpif_usage = """
Usage:
trampi --header mpi.h --header-patch mpi.h.patch --stubs mpilib.c --stubs-extra f2c_abi_stubs.c -o build/
"""
    mpif_workflow = """
Build workflow:
1. Generate mpi_proxy.c (combines mpilib.c + f2c_abi_stubs.c, applies header patch)
2. Build the library with the patched mpi.h
3. Install both the library and patched mpi.h
"""

    if args.header_patch and not args.stubs_extra:
        print("ERROR: --header-patch requires --stubs-extra")
        print("The extra stubs file (e.g., f2c_abi_stubs.c) must implement all functions declared in the header patch.")
        print(mpif_usage)
        print(mpif_workflow)
        sys.exit(1)

    if args.stubs_extra and not args.header_patch:
        print("ERROR: --stubs-extra requires --header-patch")
        print("Extra stubs file must be accompanied by a header patch that declares the functions it implements.")
        print(mpif_usage)
        print(mpif_workflow)
        sys.exit(1)

    print(f"Reading {args.header}")
    functions = parse_header(args.header)

    extension_functions = []
    if args.header_patch:
        print(mpif_workflow)
        verify_header_patch(args.header_patch)
        print(f"Reading {args.header_patch}")
        extension_functions = parse_header_patch(args.header_patch)

        # Place the patched mpi.h alongside the generated mpi_proxy.c
        patched_header_path = output_dir / "mpi.h"
        apply_header_patch(
            args.header,
            args.header_patch,
            patched_header_path,
        )

    # Handle extra stubs files if provided
    stubs_path = args.stubs
    if args.stubs_extra:
        print(f"Reading extra stubs {args.stubs_extra}")

        # Extract function names from original stubs
        def extract_functions(filepath):

            funcs = set()
            with open(filepath, "r") as f:
                for line in f:
                    m = re.search(r"\b(MPI|PMPI)_[A-Za-z0-9_]+\s*\(", line)
                    if m:
                        funcs.add(m.group(0).rstrip("("))
            return funcs

        orig_funcs = extract_functions(args.stubs)

        # Concatenate extra file(s) to a temporary copy
        combined_stubs_path = output_dir / "mpilib_combined.c"

        with open(args.stubs, "r") as orig, open(combined_stubs_path, "w") as combined:
            combined.write(orig.read())
            combined.write("\n\n/* Additional stubs from: " + args.stubs_extra + " */\n")
            with open(args.stubs_extra, "r") as extra:
                for line in extra:
                    if line.lstrip().startswith("#include"):
                        continue
                    combined.write(line)

        # Extract function names from extra file
        extra_funcs = extract_functions(args.stubs_extra)

        # Check for duplicates with original stubs (linker error)
        duplicates = orig_funcs & extra_funcs
        if duplicates:
            print(f"WARNING: {len(duplicates)} functions defined in both files:")
            for fn in sorted(duplicates):
                print(f"  - {fn}")
            print("These may cause duplicate symbol errors at link time.")

        # Check that all functions in extra stubs are declared in header patch
        extension_func_names = {f.name for f in extension_functions}
        undeclared = extra_funcs - extension_func_names
        if undeclared:
            print(f"ERROR: {len(undeclared)} functions in extra stubs not declared in header patch:")
            for fn in sorted(undeclared):
                print(f"  - {fn}")
            print("Extra stubs file must only implement functions declared in the header patch.")
            sys.exit(1)

        stubs_path = combined_stubs_path
        print(f"Extra stubs: all {len(extra_funcs)} functions declared in header patch, {len(duplicates)} duplicates")

    print(f"Reading {stubs_path}")

    emit_proxy(
        functions=functions,
        extension_functions=extension_functions,
        mpi_stubs=stubs_path,
        output=output_path,
    )

    written = [output_path]
    if args.header_patch:
        written.append(output_dir / "mpi.h")

    verb = "has" if len(written) == 1 else "have"
    print(f"{' and '.join(str(p) for p in written)} {verb} been written.")

    # Summary of function sources
    print()
    print("Function source summary:")
    print(f"  Base functions (from mpi.h): {len(functions)}")
    print(f"  Extension functions (from header patch): {len(extension_functions)}")
    print()
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
