"""
mpi_parser.py

Read mpi.h and build a list of MPI functions.
"""

from dataclasses import dataclass
import re

from .tokenizer import parse_prototype, extract_identifier

##############################################################################
# Model
##############################################################################


@dataclass
class Parameter:

    declaration: str
    name: str


@dataclass
class Function:

    return_type: str
    name: str
    parameters: list

    @property
    def prototype(self):

        if self.parameters:

            args = ", ".join(p.declaration for p in self.parameters)

        else:

            args = "void"

        return f"{self.return_type} " f"{self.name}" f"({args})"


##############################################################################
# Reading mpi.h
##############################################################################


def read_prototypes(lines):
    """
    Collect complete MPI/PMPI prototypes.

    Multi-line declarations become one string.
    """

    prototypes = []

    collecting = False

    current = []

    for line in lines:

        stripped = line.strip()

        # Skip blank lines.
        if not stripped:
            continue

        # Skip comments.
        if stripped.startswith("/*"):
            continue

        # Skip preprocessor directives.
        if stripped.startswith("#"):
            continue

        if not collecting:

            # Only start collecting if this line contains the
            # beginning of an MPI/PMPI function declaration.
            if not re.search(r"\b(?:MPI_|PMPI_)\w+\s*\(", line):
                continue
            collecting = True
            current = [stripped]

            if ";" in line:

                prototypes.append(" ".join(current))

                collecting = False

        else:

            current.append(stripped)

            if ";" in line:

                prototypes.append(" ".join(current))

                collecting = False

    return prototypes


def read_header_prototypes(filename):
    with open(filename, encoding="utf8") as f:
        return read_prototypes(f)


def read_patch_prototypes(filename):

    added_lines = []

    with open(filename, encoding="utf8") as f:

        for line in f:

            # Ignore patch metadata.
            if line.startswith(("+++", "---", "@@")):
                continue

            # Keep only added lines.
            if line.startswith("+"):
                added_lines.append(line[1:])

    # Reuse the same prototype reader on the filtered lines.
    return read_prototypes(added_lines)


##############################################################################
# Parsing
##############################################################################


def parse_prototypes(prototypes):

    functions = []

    for prototype in prototypes:

        prototype = prototype.strip()

        try:

            return_type, name, params = parse_prototype(prototype)

        except Exception:

            print()
            print("Unable to parse prototype:")
            print(prototype)
            raise

        parameter_objects = [
            Parameter(
                declaration=p,
                name=extract_identifier(p),
            )
            for p in params
        ]

        functions.append(
            Function(
                return_type=return_type,
                name=name,
                parameters=parameter_objects,
            )
        )

    return functions


def parse_header(filename):

    return parse_prototypes(read_header_prototypes(filename))


def parse_header_patch(filename):

    return parse_prototypes(read_patch_prototypes(filename))
