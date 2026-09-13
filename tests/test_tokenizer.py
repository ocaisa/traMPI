"""
Unit tests for trampi.tokenizer.

These are pure text-in/text-out tests and need no MPI installation.
"""

import pytest

from trampi.tokenizer import (
    extract_identifier,
    find_matching,
    normalize_whitespace,
    parse_prototype,
    split_parameters,
    split_return_type_and_name,
)


def test_normalize_whitespace():
    # Tabs and runs of spaces become single spaces; ends are stripped.
    assert normalize_whitespace("  int   MPI_Foo\t(MPI_Comm  comm, int *rank);  ") == \
        "int MPI_Foo (MPI_Comm comm, int *rank);"


def test_find_matching_nested_parentheses():
    assert find_matching("foo(bar(baz), x)", 3) == 15


def test_find_matching_single_level():
    assert find_matching("foo(1, 2)", 3) == 8


def test_find_matching_unmatched_raises():
    with pytest.raises(ValueError, match="Unmatched delimiter"):
        find_matching("foo(bar(baz)", 3)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("void", []),
        ("int a[][3], int (*fn)(int), const char *name",
         ["int a[][3]", "int (*fn)(int)", "const char *name"]),
        (" int , double *p ", ["int", "double *p"]),
    ],
)
def test_split_parameters(text, expected):
    assert split_parameters(text) == expected


@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        ("int x", "x"),
        ("MPI_Comm *comm", "comm"),
        ("int ranges[][3]", "ranges"),
        ("char name[32]", "name"),
        ("const int *restrict ptr", "ptr"),
        ("...", None),
    ],
)
def test_extract_identifier(declaration, expected):
    assert extract_identifier(declaration) == expected


def test_extract_identifier_rejects_function_pointers():
    with pytest.raises(ValueError, match="Function pointer"):
        extract_identifier("int (*fn)(int)")


def test_split_return_type_and_name():
    assert split_return_type_and_name("int MPI_Comm_rank") == ("int", "MPI_Comm_rank")
    assert split_return_type_and_name("MPI_Comm MPI_Comm_fromint") == ("MPI_Comm", "MPI_Comm_fromint")
    assert split_return_type_and_name("double MPI_Wtime") == ("double", "MPI_Wtime")


def test_split_return_type_and_name_without_name_raises():
    with pytest.raises(ValueError):
        split_return_type_and_name("int")


def test_parse_prototype_basic():
    assert parse_prototype("int MPI_Comm_rank(MPI_Comm comm, int *rank);") == \
        ("int", "MPI_Comm_rank", ["MPI_Comm comm", "int *rank"])


def test_parse_prototype_without_trailing_semicolon():
    assert parse_prototype("int MPI_Comm_rank(MPI_Comm comm, int *rank)") == \
        ("int", "MPI_Comm_rank", ["MPI_Comm comm", "int *rank"])


def test_parse_prototype_void():
    assert parse_prototype("void MPI_Finalize(void);") == ("void", "MPI_Finalize", [])


def test_parse_prototype_variadic():
    assert parse_prototype("int MPI_Pcontrol(const int level, ...);") == \
        ("int", "MPI_Pcontrol", ["const int level", "..."])


def test_parse_prototype_many_params():
    prototype = (
        "int MPI_Alltoallv(const void *sendbuf, const int *sendcounts, const int *sdispls, "
        "void *recvbuf, const int *recvcounts, const int *rdispls, MPI_Datatype datatype, MPI_Comm comm);"
    )
    assert parse_prototype(prototype) == (
        "int",
        "MPI_Alltoallv",
        [
            "const void *sendbuf",
            "const int *sendcounts",
            "const int *sdispls",
            "void *recvbuf",
            "const int *recvcounts",
            "const int *rdispls",
            "MPI_Datatype datatype",
            "MPI_Comm comm",
        ],
    )
