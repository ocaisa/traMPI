import re

VARIADIC_FUNCTIONS = {
    "MPI_Pcontrol",
    "PMPI_Pcontrol",
}


def read_mpi_stubs(source):
    """
    Return mpilib.c as a list of lines.

    The file is read verbatim.
    """

    with open(source, encoding="utf8") as f:
        return f.readlines()


def inject_runtime_support(out, base_functions, extension_functions):
    all_functions = base_functions + extension_functions
    out.write("""
#include <dlfcn.h>
#include <stdlib.h>
#include <stdio.h>

/* Declare the GNU dlmopen() interface without enabling _GNU_SOURCE for the
 * entire translation unit. This avoids changing the feature set exposed by
 * other system headers such as mpi.h.
 */
#if defined(__GLIBC__) && !defined(LM_ID_NEWLM)
typedef long int Lmid_t;
#define LM_ID_NEWLM ((Lmid_t)-1)
extern void *dlmopen(Lmid_t nsid, const char *filename, int flags);
#endif

#if defined(__GLIBC__) && !__GLIBC_PREREQ(2,34)
#error "TRAMPI requires glibc >= 2.34 otherwise it would require linking with -ldl. glibc < 2.34 is intentionally unsupported."
#endif

#ifndef DEFAULT_TRAMPI_ABI_LIBRARY
#define DEFAULT_TRAMPI_ABI_LIBRARY NULL
#endif

""")

    #
    # Typedefs
    #
    for fn in all_functions:
        params = ", ".join(p.declaration for p in fn.parameters) or "void"
        out.write(f"typedef {fn.return_type} " f"(*fn_{fn.name}_t)({params});\n")

    out.write("\n")

    #
    # Backend pointers
    #
    for fn in all_functions:
        out.write(f"static fn_{fn.name}_t backend_{fn.name} = NULL;\n")

    out.write(r"""

static void __attribute__((constructor))
init_mpi_proxy(void)
{
    const char *lib;
    const char *verbose;
    const char *force_dlopen;
    void *handle;
    void *sym;
    int missing_symbols = 0;
    int missing_ext_symbols = 0;

    verbose = getenv("TRAMPI_ABI_LIBRARY_VERBOSE");
    lib = getenv("TRAMPI_ABI_LIBRARY");
    force_dlopen = getenv("TRAMPI_FORCE_DLOPEN");

    if (!lib)
        lib = DEFAULT_TRAMPI_ABI_LIBRARY;


    if (!lib) {
        fprintf(stderr,
            "TRAMPI:: No MPI backend configured. Please set the environment variable TRAMPI_ABI_LIBRARY to an MPI ABI-compliant library\n");
        abort();
    }

#if defined(__GLIBC__)
    if (!force_dlopen || force_dlopen[0] == '\0') {
        if (verbose) {
            fprintf(stderr,
                    "TRAMPI:: Loading MPI backend in an isolated linker namespace via dlmopen().\n");
        }
        handle = dlmopen(LM_ID_NEWLM, lib, RTLD_NOW | RTLD_LOCAL);
    } else {
        if (verbose) {
            fprintf(stderr,
                    "TRAMPI:: TRAMPI_FORCE_DLOPEN is set; using dlopen().\n");
        }
        handle = dlopen(lib, RTLD_NOW | RTLD_GLOBAL);
    }
#else
    if (verbose && force_dlopen) {
        fprintf(stderr,
                "TRAMPI:: TRAMPI_FORCE_DLOPEN ignored (dlmopen unavailable).\n");
    }
    if (verbose) {
        fprintf(stderr,
                "TRAMPI:: Loading MPI backend in an isolated linker namespace via dlopen().\n");
    }
    handle = dlopen(lib, RTLD_NOW | RTLD_GLOBAL);
#endif

    if (!handle) {
        fprintf(stderr,
                "TRAMPI:: %s\n",
                dlerror());
        abort();
    }

    if (verbose) {
        fprintf(stderr, "TRAMPI:: Loaded backend MPI ABI library %s\n", lib);
    }

""")

    for fn in base_functions:
        out.write(f'    sym = dlsym(handle, "{fn.name}");\n')
        out.write("    if (!sym) {\n")
        out.write("        if (verbose)\n")
        out.write(f'            fprintf(stderr, "TRAMPI:: Unable to resolve {fn.name}\\n");\n')
        out.write("        ++missing_symbols;\n")
        out.write("    }\n")
        out.write(f"    *(void **)(&backend_{fn.name}) = sym;\n")
    out.write("\n")
    for fn in extension_functions:
        out.write(f'    sym = dlsym(handle, "{fn.name}");\n')
        out.write("    if (!sym) {\n")
        out.write("        if (verbose)\n")
        out.write(
            f"            fprintf(stderr, "
            f'"TRAMPI:: Optional MPI ABI extension not available in runtime: {fn.name}\\n");\n'
        )
        out.write("        ++missing_ext_symbols;\n")
        out.write("    }\n")
        out.write(f"    *(void **)(&backend_{fn.name}) = sym;\n")

    out.write("""
    if (missing_symbols && verbose) {
    fprintf(stderr,
            "TRAMPI:: Warning: %d required MPI ABI symbols could not be resolved. "
            "Calls to these functions will fail.\\n",
            missing_symbols);
    }

    if (missing_ext_symbols && verbose) {
        fprintf(stderr,
                "TRAMPI:: Warning: %d optional MPI ABI extension symbols could not be resolved. "
                "These functions were added by mpif and are not available in the backend MPI library. "
                "Calls to these functions will fail.\\n",
                missing_ext_symbols);
    }
}

""")


def wrapper_body(fn):

    if fn.name in VARIADIC_FUNCTIONS:

        return (
            f'fprintf(stderr, "{fn.name}: '
            'cannot automatically forward variadic arguments\\n"); '
            "return MPI_SUCCESS; "
        )

    call = ", ".join(p.name for p in fn.parameters if p.name)

    if fn.return_type == "void":
        return f"backend_{fn.name}({call}); "

    return f"return backend_{fn.name}({call}); "


def emit_wrapper(out, fn):

    params = ", ".join(p.declaration for p in fn.parameters) or "void"

    out.write(f"{fn.return_type} {fn.name}({params}) ")
    out.write("{ ")

    out.write(wrapper_body(fn))

    out.write("}\n")


def rewrite_mpi_stubs(lines, functions):
    """
    Rewrite the bodies of MPI/PMPI functions while preserving the rest
    of mpilib.c unchanged.

    Returns the rewritten lines and the names of the functions that were
    not found in the stubs.
    """

    lookup = {fn.name: fn for fn in functions}

    pattern = re.compile(r"\b(" + "|".join(re.escape(fn.name) for fn in functions) + r")\s*\(")

    out = []

    found = set()

    i = 0

    while i < len(lines):

        line = lines[i]

        m = pattern.search(line)

        #
        # Not an MPI function.
        #
        if m is None:
            out.append(line)
            i += 1
            continue

        fn = lookup[m.group(1)]

        found.add(fn.name)

        #
        # Copy the signature up to and including the opening brace.
        #
        while True:

            line = lines[i]

            if "{" in line:

                brace = line.index("{")

                #
                # Preserve everything through the opening brace.
                #
                out.append(line[: brace + 1] + " ")

                #
                # One-line function?
                #
                if "}" in line[(brace + 1):]:
                    i += 1
                    break

                i += 1

                #
                # Skip the original body.
                #
                depth = 1

                while i < len(lines) and depth:

                    depth += lines[i].count("{")
                    depth -= lines[i].count("}")

                    i += 1

                break

            out.append(line)
            i += 1

        #
        # Emit replacement body.
        #
        # Record source: original MPI ABI function (may be modified by stubs patch)

        out.append(wrapper_body(fn))

        #
        # Close the function.
        #
        out.append("}\n")

    missing = [name for name in lookup if name not in found]

    return out, missing


def emit_proxy(
    *,
    functions,
    extension_functions,
    mpi_stubs,
    output,
):
    """Emit the trampoline C file with source-tracking comments.

    Args:
        functions: List of base MPI functions from mpi.h
        extension_functions: List of additional functions from header patch
        mpi_stubs: Path to mpilib.c (possibly combined with extra files)
        output: Output file path
    """

    lines = read_mpi_stubs(mpi_stubs)

    rewritten, missing = rewrite_mpi_stubs(lines, functions + extension_functions)

    if missing:
        raise RuntimeError(
            f"No wrapper found in {mpi_stubs} for: {', '.join(sorted(missing))}"
        )

    insert_after = -1

    for i, line in enumerate(rewritten):
        if line.lstrip().startswith("#include"):
            insert_after = i

    if insert_after == -1:
        raise RuntimeError("No #include directives found.")

    with open(output, "w", encoding="utf8") as out:
        # Write source-tracking header comment
        out.write("/*\n")
        out.write(" * MPI ABI Trampoline - Function Source Tracking\n")
        out.write(" * Generated by traMPI\n")

        # Header patch info (extension functions)
        if extension_functions:
            out.write(" *\n")
            out.write(" * Functions added by header patch (extension functions):\n")
            for fn in sorted(f.name for f in extension_functions):
                out.write(f" *   + {fn}\n")

        out.write(" */\n\n")
        for i, line in enumerate(rewritten):

            out.write(line)

            if i == insert_after:
                out.write("\n")
                inject_runtime_support(out, functions, extension_functions)
                out.write("\n")
