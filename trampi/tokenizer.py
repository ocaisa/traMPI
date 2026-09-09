"""
tokenizer.py

Small utilities for tokenizing C function declarations.

No MPI-specific logic lives here.
"""

import re

##############################################################################
# Whitespace
##############################################################################

_whitespace = re.compile(r"\s+")


def normalize_whitespace(text):
    """
    Collapse whitespace into single spaces.
    """
    return _whitespace.sub(" ", text).strip()


##############################################################################
# Parenthesis matching
##############################################################################


def find_matching(text, start, open_char="(", close_char=")"):
    """
    Return the matching closing delimiter.

    Example:

        foo(bar(baz), x)

    start should point at the '('.
    """

    depth = 0

    for i in range(start, len(text)):

        c = text[i]

        if c == open_char:
            depth += 1

        elif c == close_char:

            depth -= 1

            if depth == 0:
                return i

    raise ValueError("Unmatched delimiter")


##############################################################################
# Parameter splitting
##############################################################################


def split_parameters(parameter_string):
    """
    Split a C parameter list.

    Correctly handles

        int a[][3]

        int (*fn)(int)

        const char name[]

    without splitting inside [] or ().
    """

    parameter_string = parameter_string.strip()

    if not parameter_string:
        return []

    if parameter_string == "void":
        return []

    params = []

    start = 0

    paren = 0
    bracket = 0

    for i, c in enumerate(parameter_string):

        if c == "(":
            paren += 1

        elif c == ")":
            paren -= 1

        elif c == "[":
            bracket += 1

        elif c == "]":
            bracket -= 1

        elif c == "," and paren == 0 and bracket == 0:

            params.append(parameter_string[start:i].strip())

            start = i + 1

    params.append(parameter_string[start:].strip())

    return params


##############################################################################
# Identifier extraction
##############################################################################

_identifier = re.compile(r"[A-Za-z_]\w*$")


def extract_identifier(declaration):
    """
    Extract the variable name from a parameter declaration.

    Examples

        int x                    -> x

        MPI_Comm *comm           -> comm

        int ranges[][3]          -> ranges

        char name[32]            -> name

    Returns None if no identifier can be found.

    Function-pointer parameters are intentionally rejected.
    """

    text = declaration.strip()

    #
    # Reject function pointers.
    #
    if "(*" in text:
        raise ValueError("Function pointer parameters are unsupported:\n" + declaration)

    #
    # Remove array extents.
    #
    while True:

        new = re.sub(r"\[[^\[\]]*\]", "", text)

        if new == text:
            break

        text = new

    #
    # Remove pointer stars.
    #
    text = text.replace("*", " ")

    m = _identifier.search(text)

    if not m:
        return None

    return m.group(0)


##############################################################################
# Prototype helpers
##############################################################################


def split_return_type_and_name(prefix):
    """
    Split

        int MPI_Comm_rank

    into

        ("int", "MPI_Comm_rank")
    """

    prefix = normalize_whitespace(prefix)

    pieces = prefix.rsplit(" ", 1)

    if len(pieces) != 2:
        raise ValueError(f"Unable to split return type and function name:\n{prefix}")

    return pieces[0], pieces[1]


##############################################################################
# Prototype parser
##############################################################################


def parse_prototype(prototype):
    """
    Parse one complete prototype.

        int MPI_Comm_rank(MPI_Comm comm, int *rank);

    Returns

        return_type
        function_name
        parameter_strings
    """

    prototype = normalize_whitespace(prototype)

    if prototype.endswith(";"):
        prototype = prototype[:-1]

    left = prototype.index("(")

    right = find_matching(prototype, left)

    prefix = prototype[:left]

    args = prototype[(left + 1): right]

    return_type, function_name = split_return_type_and_name(prefix)

    parameters = split_parameters(args)

    return return_type, function_name, parameters
