# traMPI

traMPI generates a trampoline implementation of the MPI ABI from an `mpi.h` header file and an `mpilib.c` file (which are expected to come from the [`mpi-abi-stubs` reference for the MPI standard ABI](https://github.com/mpi-forum/mpi-abi-stubs)). It also has (optional) support for [`mpif`](https://github.com/eschnett/mpif). The generated `mpi_proxy.c` (and potentially a patched `mpi.h` if using `mpif`) forwards all supported MPI and PMPI entry points to a backend MPI library that is selected at runtime. The library relies on `mpi-abi-stubs` to provide a build system.

## Why and how

traMPI scratches an itch for those who heavily use RPATH linking. An MPI ABI is only useful if you can easily switch out the active MPI backend library at runtime. This is typically done via `LD_LIBRARY_PATH`, but when you use RPATH this avenue is not open. This tool provides an ABI-compatible library that can be used for linking while still allowing for the selection of the actual backend MPI library at runtime via the environment variable `TRAMPI_ABI_LIBRARY` (which points to an MPI 5.0 ABI compatible library).

The concept is heavily influenced by the design of [`MPItrampoline`](https://github.com/eschnett/MPItrampoline) and aided in implementation by AI (so probably not perfect but works with my testing to date).

## Installation

Create and activate a Python virtual environment, then install the generator:

```bash
pip install -e .
```

This installs the `trampi` command-line tool.

## Generating the trampoline

Run the generator against the MPI ABI header and stub. For example:

Basic usage:

```bash
trampi \
    --header mpi-abi-stubs/mpi.h \
    --stubs mpi-abi-stubs/mpilib.c
```

When additional declarations are required (for example `mpif` support), supply a
unified diff that only modifies `mpi.h`:

```bash
trampi \
    --header mpi-abi-stubs/mpi.h \
    --header-patch mpif.patch \
    --stubs mpi-abi-stubs/mpilib.c
```

The patch is verified before being applied and must only contain changes to
`mpi.h`. A patched copy of the header is written alongside the generated
`mpi_proxy.c`.

> **Note**
>
> Using `--header-patch` requires the standard Unix `patch` program to be
> installed and available on your `PATH`.

The generator will:

* Parse and verify all MPI and PMPI declarations.
* Generate mpi_proxy.c. When `--header-patch` is supplied, a patched copy of
  mpi.h is also written into the output directory for use when building the
  trampoline.
* Verify that every parsed function has a corresponding wrapper.

A successful run reports the number of verified wrappers and writes `mpi_proxy.c` into the current directory.

## Building the trampoline library

The generated source can be built using the existing `mpi-abi-stubs` build system (which supports a `Makefile`, `CMake`, and `Meson`).

First, build the reference library if desired to ensure compilation succeeds in general:

```bash
cd mpi-abi-stubs
make
make clean
```

Then build the trampoline implementation by overriding the source file:

```bash
ln -s ../mpi_proxy.c  # Make a symlink to our generated code
make SOURCE_C=/path/to/mpi_proxy.c SOURCE_H=/path/to/mpi.h
```

(`SOURCE_H` is only required if using `mpif`)

A similar source override mechanism is supported by the CMake (`-DSOURCE_C=/path/to/mpi_proxy.c`, `-DSOURCE_H=/path/to/mpi.h`) and Meson (`-Dsource_c=mpi_proxy.c`, `-Dsource_h=mpi.h`) build systems.

## Output

The resulting shared library exports the same MPI/PMPI interface as the reference `mpi-abi-stubs` implementation (plus `mpif` if using this) while dispatching calls to a backend MPI library at runtime. When using the backend library you can use the environment variable `TRAMPI_ABI_LIBRARY_VERBOSE` to inspect any missing symbols from there (these will only fail if they are actually used by the application).

## Selecting the backend MPI library

The generated trampoline loads the backend MPI library at runtime using `dlopen()`.

The library to load is chosen as follows:

1. If the environment variable `TRAMPI_ABI_LIBRARY` is set, its value is used.
2. Otherwise, if `DEFAULT_TRAMPI_ABI_LIBRARY` was defined when `mpi_proxy.c` was compiled, that library is used.
3. If neither is available, initialisation fails with an error.

For example:

```bash
export TRAMPI_ABI_LIBRARY=/path/to/libmpi.so
./my_mpi_application
```

To embed a default backend library at compile time requires some awkward but necessary quoting since we don't control the build system. For the `Makefile`

```bash
export CPPFLAGS='-DDEFAULT_TRAMPI_ABI_LIBRARY=\"/path/to/libmpi_abi.so\"'
make SOURCE_C=mpi_proxy.c
```

or for CMake:

```bash
cmake -B build --install-prefix=$PWD -DSOURCE_C=mpi_proxy.c -DCMAKE_C_FLAGS='"-DDEFAULT_TRAMPI_ABI_LIBRARY=\"/path/to/libmpi_abi.so\""'
```

or for Meson:

```bash
meson setup build -Dsource_c=mpi_proxy.c -Dc_args='-DDEFAULT_TRAMPI_ABI_LIBRARY=\"/path/to/libmpi_abi.so\"'
```

This allows the trampoline to use a fixed backend by default while still permitting it to be overridden at runtime via `TRAMPI_ABI_LIBRARY`.
