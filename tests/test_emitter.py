"""
Unit tests for trampi.emitter and the trampi command line.

The emitter tests use tiny synthetic headers/stubs, so they run anywhere.
The end-to-end tests generate a real trampoline from the submodule
inputs and (when gcc is available) compile it - this verifies the
generated C without needing any MPI installation.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from trampi.emitter import emit_proxy, rewrite_mpi_stubs
from trampi.mpi_parser import parse_header, parse_header_patch, parse_prototypes

REPO_ROOT = Path(__file__).resolve().parents[1]
MPI_HEADER = REPO_ROOT / "mpi-abi-stubs" / "mpi.h"
MPI_PATCH = REPO_ROOT / "mpif" / "fortran" / "mpi.h.patch"
MPI_STUBS = REPO_ROOT / "mpi-abi-stubs" / "mpilib.c"
F2C_STUBS = REPO_ROOT / "mpif" / "fortran" / "f2c_abi_stubs.c"

SUBMODULE_FILES = (MPI_HEADER, MPI_PATCH, MPI_STUBS, F2C_STUBS)

requires_submodules = pytest.mark.skipif(
    not all(path.is_file() for path in SUBMODULE_FILES),
    reason="submodules mpi-abi-stubs and mpif are not checked out",
)
requires_patch = pytest.mark.skipif(shutil.which("patch") is None, reason="patch command is not available")

FAKE_HEADER = (
    "int MPI_Fake_fn(int *a);\n"
    "void MPI_Fake_void(void);\n"
    "int MPI_Fake_multi(\n"
    "    int *a,\n"
    "    int *b);\n"
    "int MPI_Fake_oneline(void);\n"
    "int MPI_Pcontrol(const int level, ...);\n"
)

FAKE_STUBS = """\
#include <stdio.h>

static int helper(void)
{
    return 42;
}

int MPI_Fake_fn(int *a)
{
    (void) a;
    return helper();
}

void MPI_Fake_void(void)
{
}

int MPI_Fake_multi(
    int *a,
    int *b)
{
    if (*a > 0 && *b > 0) {
        return *a + *b;
    }
    return 0;
}

int MPI_Fake_oneline(void) { return 0; }

int MPI_Pcontrol(const int level, ...)
{
    return 0;
}

int Not_MPI(void)
{
    return 1;
}
"""


def _functions(tmp_path, text=FAKE_HEADER):
    header = tmp_path / "mpi.h"
    header.write_text(text, encoding="utf8")
    return parse_header(str(header))


def test_rewrite_mpi_stubs_replaces_bodies_and_preserves_other_code(tmp_path):
    functions = _functions(tmp_path)
    rewritten, missing = rewrite_mpi_stubs(FAKE_STUBS.splitlines(keepends=True), functions)
    assert missing == []
    text = "".join(rewritten)
    # Non-MPI content survives untouched.
    assert "static int helper(void)" in text
    assert "int Not_MPI(void)" in text
    assert "return 1;" in text
    # Original bodies are gone.
    assert "return helper();" not in text
    assert "if (*a > 0" not in text
    # Replacement trampolines are in place (one-line, multi-line and variadic).
    assert "{ return backend_MPI_Fake_fn(a); }" in text
    # void functions are called, not returned.
    assert "{ backend_MPI_Fake_void(); }" in text
    assert "{ return backend_MPI_Fake_multi(a, b); }" in text
    assert "int MPI_Fake_oneline(void) { return backend_MPI_Fake_oneline(); }" in text
    assert "cannot automatically forward variadic arguments" in text
    assert "return MPI_SUCCESS;" in text


def test_rewrite_mpi_stubs_reports_missing_functions():
    functions = parse_prototypes(["int MPI_Fake_fn(int *a);", "int MPI_Unknown(void);"])
    lines = ["int MPI_Fake_fn(int *a)\n", "{\n", "    return 0;\n", "}\n"]
    _, missing = rewrite_mpi_stubs(lines, functions)
    assert missing == ["MPI_Unknown"]


def test_emit_proxy_requires_include_directives(tmp_path):
    functions = _functions(tmp_path, "int MPI_Fake_fn(int *a);\n")
    stubs = tmp_path / "mpilib.c"
    stubs.write_text("int MPI_Fake_fn(int *a)\n{\n    return 0;\n}\n", encoding="utf8")
    with pytest.raises(RuntimeError, match="No #include"):
        emit_proxy(
            functions=functions,
            extension_functions=[],
            mpi_stubs=str(stubs),
            output=tmp_path / "mpi_proxy.c",
        )


def test_emit_proxy_writes_trampolines_for_all_functions(tmp_path):
    functions = _functions(tmp_path)
    stubs = tmp_path / "mpilib.c"
    stubs.write_text(FAKE_STUBS, encoding="utf8")
    output = tmp_path / "mpi_proxy.c"
    emit_proxy(
        functions=functions,
        extension_functions=[],
        mpi_stubs=str(stubs),
        output=output,
    )
    text = output.read_text(encoding="utf8")
    assert "#include <dlfcn.h>" in text
    assert "__attribute__((constructor))" in text
    assert "TRAMPI_ABI_LIBRARY" in text
    assert "TRAMPI_FORCE_DLOPEN" in text
    for name in ["MPI_Fake_fn", "MPI_Fake_void", "MPI_Fake_multi", "MPI_Fake_oneline", "MPI_Pcontrol"]:
        assert f"static fn_{name}_t backend_{name} = NULL;" in text
        assert f'dlsym(handle, "{name}")' in text
        assert f"Unable to resolve {name}" in text


def test_emit_proxy_includes_extension_functions(tmp_path):
    functions = _functions(tmp_path, "int MPI_Fake_fn(int *a);\n")
    ext_header = tmp_path / "ext.h"
    ext_header.write_text("int PMPI_Fake_f2c(int *x);\n", encoding="utf8")
    extensions = parse_header(str(ext_header))
    stubs = tmp_path / "mpilib.c"
    stubs.write_text(
        "#include <stdio.h>\n\n"
        "int MPI_Fake_fn(int *a)\n{\n    return 0;\n}\n\n"
        "int PMPI_Fake_f2c(int *x)\n{\n    return 0;\n}\n",
        encoding="utf8",
    )
    output = tmp_path / "mpi_proxy.c"
    emit_proxy(
        functions=functions,
        extension_functions=extensions,
        mpi_stubs=str(stubs),
        output=output,
    )
    text = output.read_text(encoding="utf8")
    assert 'dlsym(handle, "PMPI_Fake_f2c")' in text
    assert "Optional MPI ABI extension not available in runtime: PMPI_Fake_f2c" in text
    assert "{ return backend_PMPI_Fake_f2c(x); }" in text
    assert " + PMPI_Fake_f2c" in text


def run_trampi(*args):
    return subprocess.run(
        [sys.executable, "-m", "trampi", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


@requires_submodules
def test_cli_rejects_header_patch_without_stubs_extra(tmp_path):
    result = run_trampi(
        "--header", str(MPI_HEADER),
        "--stubs", str(MPI_STUBS),
        "--header-patch", str(MPI_PATCH),
        "-o", str(tmp_path / "out"),
    )
    assert result.returncode == 1
    assert "--header-patch requires --stubs-extra" in result.stdout


@requires_submodules
def test_cli_rejects_stubs_extra_without_header_patch(tmp_path):
    result = run_trampi(
        "--header", str(MPI_HEADER),
        "--stubs", str(MPI_STUBS),
        "--stubs-extra", str(F2C_STUBS),
        "-o", str(tmp_path / "out"),
    )
    assert result.returncode == 1
    assert "--stubs-extra requires --header-patch" in result.stdout


def test_cli_rejects_patch_touching_other_files(tmp_path):
    header = tmp_path / "mpi.h"
    header.write_text("int MPI_Fake(void);\n", encoding="utf8")
    stubs = tmp_path / "mpilib.c"
    stubs.write_text("#include <stdio.h>\n\nint MPI_Fake(void)\n{\n    return 0;\n}\n", encoding="utf8")
    patch = tmp_path / "other.h.patch"
    patch.write_text(
        "--- a/other.h\n"
        "+++ b/other.h\n"
        "@@ -1 +1 @@\n"
        "-int MPI_Fake(void);\n"
        "+int MPI_Fake(void);\n",
        encoding="utf8",
    )
    result = run_trampi(
        "--header", str(header),
        "--stubs", str(stubs),
        "--header-patch", str(patch),
        "--stubs-extra", str(stubs),
        "-o", str(tmp_path / "out"),
    )
    assert result.returncode == 1
    assert "must modify only mpi.h" in result.stdout


def test_cli_rejects_extra_stubs_with_undeclared_functions(tmp_path):
    header = tmp_path / "mpi.h"
    header.write_text("int MPI_Fake(void);\n", encoding="utf8")
    stubs = tmp_path / "mpilib.c"
    stubs.write_text("#include <stdio.h>\n\nint MPI_Fake(void)\n{\n    return 0;\n}\n", encoding="utf8")
    patch = tmp_path / "mpi.h.patch"
    patch.write_text(
        "--- a/mpi.h\n"
        "+++ b/mpi.h\n"
        "@@ -1,1 +1,2 @@\n"
        " int MPI_Fake(void);\n"
        "+int MPI_Dec(void);\n",
        encoding="utf8",
    )
    extra = tmp_path / "extra.c"
    extra.write_text(
        "int MPI_Dec(void)\n{\n    return 0;\n}\n\n"
        "int MPI_Undec(void)\n{\n    return 0;\n}\n",
        encoding="utf8",
    )
    result = run_trampi(
        "--header", str(header),
        "--stubs", str(stubs),
        "--header-patch", str(patch),
        "--stubs-extra", str(extra),
        "-o", str(tmp_path / "out"),
    )
    assert result.returncode == 1
    assert "not declared in header patch" in result.stdout


@requires_submodules
@requires_patch
def test_cli_end_to_end_generates_proxy_and_patched_header(tmp_path):
    result = run_trampi(
        "--header", str(MPI_HEADER),
        "--stubs", str(MPI_STUBS),
        "--header-patch", str(MPI_PATCH),
        "--stubs-extra", str(F2C_STUBS),
        "-o", str(tmp_path / "out"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "out" / "mpi_proxy.c").is_file()
    assert (tmp_path / "out" / "mpi.h").is_file()
    text = (tmp_path / "out" / "mpi_proxy.c").read_text(encoding="utf8")
    expected = {fn.name for fn in parse_header(str(MPI_HEADER))} | {
        fn.name for fn in parse_header_patch(str(MPI_PATCH))
    }
    dlsymed = set(re.findall(r'dlsym\(handle, "([^"]+)"\)', text))
    assert dlsymed == expected
    assert "#include <dlfcn.h>" in text
    assert "__attribute__((constructor))" in text


@requires_submodules
@requires_patch
@pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc is not available")
def test_generated_proxy_compiles(tmp_path):
    result = run_trampi(
        "--header", str(MPI_HEADER),
        "--stubs", str(MPI_STUBS),
        "--header-patch", str(MPI_PATCH),
        "--stubs-extra", str(F2C_STUBS),
        "-o", str(tmp_path / "out"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    compiled = subprocess.run(
        [
            "gcc",
            "-c",
            "-o", str(tmp_path / "mpi_proxy.o"),
            "-I", str(tmp_path / "out"),
            str(tmp_path / "out" / "mpi_proxy.c"),
        ],
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
