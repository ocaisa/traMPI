"""
Unit tests for trampi.mpi_parser.

Tests against the real mpi-abi-stubs/mpif submodule files double as
drift alarms: if the submodules change in a way the parser cannot
handle (or the function set changes), these tests fail loudly.
"""

from pathlib import Path

import pytest

from trampi.mpi_parser import parse_header, parse_header_patch, read_patch_prototypes, read_prototypes
from trampi.tokenizer import parse_prototype

REPO_ROOT = Path(__file__).resolve().parents[1]
MPI_HEADER = REPO_ROOT / "mpi-abi-stubs" / "mpi.h"
MPI_PATCH = REPO_ROOT / "mpif" / "fortran" / "mpi.h.patch"

requires_submodules = pytest.mark.skipif(
    not (MPI_HEADER.is_file() and MPI_PATCH.is_file()),
    reason="submodules mpi-abi-stubs and mpif are not checked out",
)


def test_read_prototypes_collects_only_mpi_declarations():
    lines = [
        "typedef int MPI_Comm;",
        "/* int MPI_In_a_comment(void); */",
        "#define MPI_FOO 1",
        "int MPI_Real(void);",
        "",
        "extern int not_mpi;",
    ]
    assert read_prototypes(lines) == ["int MPI_Real(void);"]


def test_read_prototypes_joins_wrapped_declarations():
    lines = [
        "int MPI_Wrapped(",
        "    int *a,",
        "    int *b);",
    ]
    # Lines are joined with a single space, so a space follows "(".
    assert read_prototypes(lines) == ["int MPI_Wrapped( int *a, int *b);"]


def test_read_patch_prototypes_keeps_only_added_lines(tmp_path):
    patch_file = tmp_path / "mpi.h.patch"
    patch_file.write_text(
        "--- a/mpi.h\n"
        "+++ b/mpi.h\n"
        "@@ -1,1 +1,2 @@\n"
        " int MPI_Kept(void);\n"
        "+int MPI_Added(void);\n"
        "-int MPI_Removed(void);\n",
        encoding="utf8",
    )
    assert read_patch_prototypes(str(patch_file)) == ["int MPI_Added(void);"]


@requires_submodules
def test_parse_header_function_count_is_stable():
    assert len(parse_header(str(MPI_HEADER))) == 1324


@requires_submodules
def test_parse_header_known_signatures():
    fns = {fn.name: fn for fn in parse_header(str(MPI_HEADER))}
    assert fns["MPI_Init"].prototype == "int MPI_Init(int *argc, char ***argv)"
    assert fns["MPI_Abort"].prototype == "int MPI_Abort(MPI_Comm comm, int errorcode)"
    assert fns["MPI_Wtime"].prototype == "double MPI_Wtime(void)"
    assert fns["MPI_Comm_fromint"].prototype == "MPI_Comm MPI_Comm_fromint(int comm)"
    assert fns["MPI_Allreduce"].prototype == (
        "int MPI_Allreduce(const void *sendbuf, void *recvbuf, int count, "
        "MPI_Datatype datatype, MPI_Op op, MPI_Comm comm)"
    )


@requires_submodules
def test_parse_header_variadic_pcontrol():
    fns = {fn.name: fn for fn in parse_header(str(MPI_HEADER))}
    pcontrol = fns["MPI_Pcontrol"]
    assert pcontrol.return_type == "int"
    assert [p.declaration for p in pcontrol.parameters] == ["const int level", "..."]
    assert [p.name for p in pcontrol.parameters] == ["level", None]


@requires_submodules
def test_every_base_prototype_round_trips():
    for fn in parse_header(str(MPI_HEADER)):
        return_type, name, params = parse_prototype(fn.prototype + ";")
        assert (return_type, name) == (fn.return_type, fn.name)
        assert params == [p.declaration for p in fn.parameters]


@requires_submodules
def test_parse_header_patch_extension_functions():
    base_names = {fn.name for fn in parse_header(str(MPI_HEADER))}
    extensions = parse_header_patch(str(MPI_PATCH))
    assert len(extensions) == 52
    ext_names = {fn.name for fn in extensions}
    assert not (ext_names & base_names)
    assert all(name.startswith(("MPI_", "PMPI_")) for name in ext_names)


@requires_submodules
def test_every_extension_prototype_round_trips():
    for fn in parse_header_patch(str(MPI_PATCH)):
        return_type, name, params = parse_prototype(fn.prototype + ";")
        assert (return_type, name) == (fn.return_type, fn.name)
        assert params == [p.declaration for p in fn.parameters]
