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
    --header-patch mpif/fortran/mpi.h.patch \
    --stubs mpi-abi-stubs/mpilib.c \
    --stubs-extra mpif/fortran/f2c_abi_stubs.c
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

A successful run reports the number of verified wrappers and writes `mpi_proxy.c` (and, when using `--header-patch`,
`mpi.h`) into the output directory, which defaults to the current directory and can be changed with `-o/--output`.

## Building a comprehensive traMPI MPI ABI library (CMake only)

If you are seriously going to use this library, then it needs to appear like a (somewhat) complete
MPI installation, which means support for C/C++/Fortran as well as an `mpirun`/`mpiexec` launcher. You
also need a backend MPI ABI implementation **that uses RPATH to find it's dependencies** (which is the default in
tools like EasyBuild and Spack). A full installation is a multi-step process.

Your (default) backend library needs to patched for [`mpif`](https://github.com/eschnett/mpif) to enable Fortran
support for the MPI ABI. This is out of scope to describe how to do that here, but take a look at
the MPICH/OpenMPI builds in the `easyconfig` subdirectory, or look at the build scripts for MPICH/OpenMPI under the
[`mpif` repository](https://github.com/eschnett/mpif/tree/main/ci-scripts).

```bash
# Configure and build traMPI with a default backend
cmake -S . -B build -DCMAKE_INSTALL_PREFIX=$PWD/install \
      -DTRAMPI_DEFAULT_ABI_LIBRARY="$EBROOTMPICH/lib/libmpi_abi.so" \
      -DTRAMPI_DEFAULT_MPIRUN="$EBROOTMPICH/bin/mpirun" \
      -DTRAMPI_DEFAULT_MPIEXEC="$EBROOTMPICH/bin/mpiexec"
cmake --build build
cmake --install build
```

```bash
# build the mpif bindings against the installed traMPI (forcing mpif to recognise traMPI as the MPI ABI)
cmake -S mpif -B mpif/build \
      -DMPI_C_COMPILER=$PWD/install/bin/mpicc_abi \
      -DMPI_HOME=$PWD/install \
      -DCMAKE_PREFIX_PATH=$PWD/install \
      -DCMAKE_INSTALL_PREFIX=$PWD/install
cmake --build mpif/build
```

```bash
# Optional: run the mpif test suite
cmake -S mpif/test -B mpif/test/build \
      -DCMAKE_PREFIX_PATH=$PWD/install \
      -DCMAKE_INSTALL_PREFIX=$PWD/install
cmake --build mpif/test/build

# Run the tests (requires a default backend library set as this runs real MPI code)
cd mpif/test/build && make test
```

### Building the traMPI MPI ABI library only

The generated source can be built using the `mpi-abi-stubs` build system. The preferred method is CMake:

```bash
# Configure and build with CMake
cmake -S . -B build -DCMAKE_INSTALL_PREFIX=$PWD/install \
      -DSOURCE_C=mpi_proxy.c -DSOURCE_H=mpi.h   # add SOURCE_H only if you used a header patch
cmake --build build
cmake --install build
```

If you prefer the legacy Makefile or Meson, the same overrides are available:

```bash
# Makefile
make SOURCE_C=mpi_proxy.c SOURCE_H=mpi.h   # SOURCE_H optional

# Meson
meson setup build -Dsource_c=mpi_proxy.c -Dsource_h=mpi.h
meson compile -C build
```

Embedding a default backend library at compile time requires some awkward but
necessary quoting since we don't control the build system. For the `Makefile`

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

This allows the trampoline to use a fixed backend by default while still permitting it to be overridden at runtime via
`TRAMPI_ABI_LIBRARY`.

## Output

The resulting shared library exports the same MPI/PMPI interface as the reference `mpi-abi-stubs` implementation
(plus `mpif` if using this) while dispatching calls to a backend MPI library at runtime. When using the backend
library you can use the environment variable `TRAMPI_ABI_LIBRARY_VERBOSE` to inspect any missing symbols from there
(these will only fail if they are actually used by the application).

## Selecting the backend MPI library

The generated trampoline loads the backend MPI library at runtime using `dlmopen()` (if available) or `dlopen()`. You
can always force the use of `dlopen()` by setting the environment variable `TRAMPI_FORCE_DLOPEN` (this is _required_
when using OpenMPI as a backend).

The library to load is chosen as follows:

1. If the environment variable `TRAMPI_ABI_LIBRARY` is set, its value is used.
2. Otherwise, if `DEFAULT_TRAMPI_ABI_LIBRARY` was defined when `mpi_proxy.c` was compiled, that library is used.
3. If neither is available, initialisation fails with an error.

For example:

```bash
export TRAMPI_ABI_LIBRARY=/path/to/libmpi_abi.so
mpiexec -n 2 ./my_mpi_application
```
