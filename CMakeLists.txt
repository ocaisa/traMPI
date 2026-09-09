cmake_minimum_required(VERSION 3.16...4.3)

project(traMPI LANGUAGES C CXX)

include(GNUInstallDirs)

set(TRAMPI_DEFAULT_ABI_LIBRARY "" CACHE STRING
  "Default backend MPI library (e.g. /path/to/libmpi_abi.so); may be overridden at run time with TRAMPI_ABI_LIBRARY")
set(TRAMPI_DEFAULT_MPIRUN "" CACHE STRING
  "Default launcher for the installed mpirun wrapper; may be overridden at run time with TRAMPI_ABI_LIBRARY_MPIRUN")
set(TRAMPI_DEFAULT_MPIEXEC "" CACHE STRING
  "Default launcher for the installed mpiexec wrapper; may be overridden at run time with TRAMPI_ABI_LIBRARY_MPIEXEC")

option(RELOCATABLE "Relocatable install" FALSE)

find_package(Python3 REQUIRED COMPONENTS Interpreter)

# ---------------------------------------------------------------------------
# Generate mpi_proxy.c and mpi.h from the mpi-abi-stubs sources, the mpif
# Fortran header patch, and the mpif Fortran-to-C ABI stubs.
# ---------------------------------------------------------------------------

set(TRAMPI_GENERATED_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)
set(TRAMPI_PROXY_SOURCE ${TRAMPI_GENERATED_DIR}/mpi_proxy.c)
set(TRAMPI_GENERATED_HEADER ${TRAMPI_GENERATED_DIR}/mpi.h)

file(GLOB TRAMPI_PYTHON_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/trampi/*.py)

add_custom_command(
  OUTPUT ${TRAMPI_PROXY_SOURCE} ${TRAMPI_GENERATED_HEADER}
  COMMAND ${CMAKE_COMMAND} -E make_directory ${TRAMPI_GENERATED_DIR}
  COMMAND ${Python3_EXECUTABLE} -m trampi
    --header ${CMAKE_CURRENT_SOURCE_DIR}/mpi-abi-stubs/mpi.h
    --header-patch ${CMAKE_CURRENT_SOURCE_DIR}/mpif/fortran/mpi.h.patch
    --stubs ${CMAKE_CURRENT_SOURCE_DIR}/mpi-abi-stubs/mpilib.c
    --stubs-extra ${CMAKE_CURRENT_SOURCE_DIR}/mpif/fortran/f2c_abi_stubs.c
    -o ${TRAMPI_GENERATED_DIR}
  DEPENDS
    ${TRAMPI_PYTHON_SOURCES}
    ${CMAKE_CURRENT_SOURCE_DIR}/mpi-abi-stubs/mpi.h
    ${CMAKE_CURRENT_SOURCE_DIR}/mpi-abi-stubs/mpilib.c
    ${CMAKE_CURRENT_SOURCE_DIR}/mpif/fortran/mpi.h.patch
    ${CMAKE_CURRENT_SOURCE_DIR}/mpif/fortran/f2c_abi_stubs.c
  WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
  COMMENT "Generating traMPI trampoline (mpi_proxy.c and mpi.h)"
  VERBATIM
)

# ---------------------------------------------------------------------------
# libmpi_abi
# ---------------------------------------------------------------------------

# The ABI version is taken from the (unpatched) mpi-abi-stubs header, since
# the mpif header patch only adds declarations.
function(get_version header name outvar)
  set(regex "^[ \t]*#[ \t]*define[ \t]+${name}[ \t]+([0-9]+)[ \t]*$")
  file(STRINGS ${header} value REGEX ${regex})
  if("${value}" STREQUAL "")
    message(FATAL_ERROR "${name} not found in ${header}")
  endif()
  string(REGEX REPLACE ${regex} "\\1" value ${value})
  set(${outvar} ${value} PARENT_SCOPE)
endfunction()
get_version(${CMAKE_CURRENT_SOURCE_DIR}/mpi-abi-stubs/mpi.h MPI_ABI_VERSION ABI_MAJOR)

set(LIBNAME mpi_abi)
add_library(${LIBNAME} SHARED ${TRAMPI_PROXY_SOURCE} $<$<PLATFORM_ID:Windows>:mpi-abi-stubs/mpilib.def>)
set_target_properties(
  ${LIBNAME} PROPERTIES
  SOVERSION ${ABI_MAJOR}
  MACHO_COMPATIBILITY_VERSION 0
  MACHO_CURRENT_VERSION 0
  DLL_NAME_WITH_SOVERSION FALSE
)

if(TRAMPI_DEFAULT_ABI_LIBRARY)
  target_compile_definitions(${LIBNAME} PRIVATE "DEFAULT_TRAMPI_ABI_LIBRARY=\"${TRAMPI_DEFAULT_ABI_LIBRARY}\"")
endif()

if(APPLE AND CMAKE_VERSION VERSION_LESS 3.17.0)
  get_target_property(v1 ${LIBNAME} MACHO_COMPATIBILITY_VERSION)
  get_target_property(v2 ${LIBNAME} MACHO_CURRENT_VERSION)
  set(ldflags "-compatibility_version,${v1},-current_version,${v2}")
  if(CMAKE_VERSION VERSION_LESS 3.12.0)
    set_target_properties(${LIBNAME} PROPERTIES LINK_FLAGS "-Wl,${ldflags}")
  else()
    target_link_options(${LIBNAME} PRIVATE "LINKER:${ldflags}")
  endif()
endif()

if(WIN32 AND CMAKE_VERSION VERSION_LESS 3.27.0)
  get_target_property(versioned_dll_name ${LIBNAME} DLL_NAME_WITH_SOVERSION)
  if(versioned_dll_name)
    set_target_properties(
      ${LIBNAME} PROPERTIES
      ARCHIVE_OUTPUT_NAME ${LIBNAME}
      RUNTIME_OUTPUT_NAME ${LIBNAME}-${ABI_MAJOR}
    )
  endif()
endif()

install(
  TARGETS ${LIBNAME}
  RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
)
install(FILES ${TRAMPI_GENERATED_HEADER} DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

# mpif is built and tested separately after traMPI is installed.
# Example usage after `make install`:
#   mkdir ../mpif-build && cd ../mpif-build
#   cmake -S ../traMPI/mpif -B . -DCMAKE_PREFIX_PATH=../traMPI/install -DMPI_HOME=../traMPI/install
#   make && ctest -C Release


# ---------------------------------------------------------------------------
# Compiler wrappers (mpicc, mpicxx and their _abi symlinks)
# ---------------------------------------------------------------------------

if(RELOCATABLE)
  set(prefix "$(CDPATH='' cd -- \"$(dirname -- \"$0\")\"/.. && pwd)")
  set(bindir $prefix/${CMAKE_INSTALL_BINDIR})
  set(incdir $prefix/${CMAKE_INSTALL_INCLUDEDIR})
  set(libdir $prefix/${CMAKE_INSTALL_LIBDIR})
else()
  set(prefix \"${CMAKE_INSTALL_PREFIX}\")
  if(IS_ABSOLUTE ${CMAKE_INSTALL_BINDIR})
    set(bindir \"${CMAKE_INSTALL_FULL_BINDIR}\")
  else()
    set(bindir $prefix/${CMAKE_INSTALL_BINDIR})
  endif()
  if(IS_ABSOLUTE ${CMAKE_INSTALL_INCLUDEDIR})
    set(incdir \"${CMAKE_INSTALL_FULL_INCLUDEDIR}\")
  else()
    set(incdir $prefix/${CMAKE_INSTALL_INCLUDEDIR})
  endif()
  if(IS_ABSOLUTE ${CMAKE_INSTALL_LIBDIR})
    set(libdir \"${CMAKE_INSTALL_FULL_LIBDIR}\")
  else()
    set(libdir $prefix/${CMAKE_INSTALL_LIBDIR})
  endif()
endif()
if(WIN32)
  set(rpath $bindir)
else()
  set(rpath $libdir)
endif()

# The default compiler for each wrapper is the toolchain compiler in use.
set(mpicc.CC CC)
set(mpicc.cc $ENV{CC})
set(mpicc.op cc)
set(mpicxx.CC CXX)
set(mpicxx.cc $ENV{CXX})
set(mpicxx.op cxx)
set(permissions
  OWNER_READ OWNER_WRITE OWNER_EXECUTE
  GROUP_READ GROUP_EXECUTE
  WORLD_READ WORLD_EXECUTE
)
foreach(script mpicc mpicxx)
  set(CC ${${script}.CC})
  set(cc ${${script}.cc})
  set(op ${${script}.op})
  configure_file(wrappers/mpicc.in ${script} @ONLY)
  install(
    FILES ${CMAKE_CURRENT_BINARY_DIR}/${script}
    PERMISSIONS ${permissions}
    DESTINATION ${CMAKE_INSTALL_BINDIR}
  )
  # The relative name makes the installed symlink relative to the link location.
  file(CREATE_LINK
    ${script} ${CMAKE_CURRENT_BINARY_DIR}/${script}_abi
    SYMBOLIC COPY_ON_ERROR
  )
  install(
    FILES ${CMAKE_CURRENT_BINARY_DIR}/${script}_abi
    PERMISSIONS ${permissions}
    DESTINATION ${CMAKE_INSTALL_BINDIR}
  )
endforeach()

# ---------------------------------------------------------------------------
# Launchers (mpirun, mpiexec)
# ---------------------------------------------------------------------------

set(DEFAULT_MPIRUN ${TRAMPI_DEFAULT_MPIRUN})
set(DEFAULT_MPIEXEC ${TRAMPI_DEFAULT_MPIEXEC})
foreach(script mpirun mpiexec)
  configure_file(wrappers/${script}.in ${script} @ONLY)
  install(
    FILES ${CMAKE_CURRENT_BINARY_DIR}/${script}
    PERMISSIONS ${permissions}
    DESTINATION ${CMAKE_INSTALL_BINDIR}
  )
endforeach()
