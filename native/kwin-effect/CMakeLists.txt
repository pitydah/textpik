# Builds the TextPik KWin placement effect.
#
# The effect is optional: TextPik keeps working (with unverified placement) when
# this target is not built, so packaging should only enable it when the KWin and
# KF6 development headers are present.
#
# Distributions that ship the KF6 CMake packages can enable -DUSE_KF6_CMAKE=ON;
# otherwise the dependencies are resolved directly from the include/library
# trees, which is what a flat runtime image provides.

cmake_minimum_required(VERSION 3.20)

project(textpik-kwin-effect LANGUAGES CXX)

# KWin 6.7 ships a constexpr default constructor that leaves its members
# uninitialised (core/rect.h). That is what KWin itself is built with under
# C++20, where it is valid, but C++17 rejects it, so the effect has to use the
# same standard as the compositor it links against.
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_INCLUDE_CURRENT_DIR ON)

option(TEXTPIK_USE_KF6_CMAKE "Resolve KF6 through its CMake packages" OFF)
option(TEXTPIK_BUILD_KWIN_EFFECT "Build the optional KWin placement effect" ON)

if(NOT TEXTPIK_BUILD_KWIN_EFFECT)
  return()
endif()

if(TEXTPIK_USE_KF6_CMAKE)
  find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets DBus)
  find_package(KF6 6.5 REQUIRED COMPONENTS CoreAddons)
  set(TEXTPIK_KF6_LIBS KF6::CoreAddons Qt6::Core Qt6::Gui Qt6::Widgets Qt6::DBus)
  set(TEXTPIK_KF6_INCLUDES "")
else()
  find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets DBus)

  find_path(KCOREADDONS_INCLUDE_DIR
    NAMES kpluginfactory.h
    PATH_SUFFIXES KF6/KCoreAddons
  )
  find_library(KCOREADDONS_LIBRARY NAMES KF6CoreAddons KF6CoreAddons6)

  # kwin/effect/effect.h pulls in <KSharedConfig>, which lives in KConfigCore.
  # kconfig_version.h lives one level up, next to the KF6/KConfigCore headers.
  find_path(KCONFIGCORE_INCLUDE_DIR
    NAMES ksharedconfig.h
    PATH_SUFFIXES KF6/KConfigCore
  )
  find_path(KCONFIGCORE_VERSION_INCLUDE_DIR
    NAMES kconfig_version.h
    PATH_SUFFIXES KF6/KConfig
  )

  # kwin/workspace.h includes <netwm_def.h> from KWindowSystem.
  find_path(KWINDOWSYSTEM_INCLUDE_DIR
    NAMES netwm_def.h
    PATH_SUFFIXES KF6/KWindowSystem
  )
  find_library(KCONFIGCORE_LIBRARY NAMES KF6ConfigCore KF6ConfigCore6)

  if(NOT KCOREADDONS_INCLUDE_DIR OR NOT KCOREADDONS_LIBRARY)
    message(FATAL_ERROR
      "KCoreAddons development files not found. Install the KF6 CoreAddons "
      "development package or configure with -DTEXTPIK_BUILD_KWIN_EFFECT=OFF.")
  endif()

  if(NOT KCONFIGCORE_INCLUDE_DIR OR NOT KCONFIGCORE_LIBRARY)
    message(FATAL_ERROR
      "KConfigCore development files not found (required by kwin's effect "
      "headers). Configure with -DTEXTPIK_BUILD_KWIN_EFFECT=OFF.")
  endif()

  set(TEXTPIK_KF6_LIBS ${KCOREADDONS_LIBRARY} ${KCONFIGCORE_LIBRARY})
  set(TEXTPIK_KF6_INCLUDES
    ${KCOREADDONS_INCLUDE_DIR}
    ${KCONFIGCORE_INCLUDE_DIR}
    ${KCONFIGCORE_VERSION_INCLUDE_DIR}
    ${KWINDOWSYSTEM_INCLUDE_DIR})
endif()

# KWin ships its headers as a plain include tree and exposes no pkg-config file.
# The effect's includes are written as <effect/effect.h> and <window.h>, so the
# include root has to be the kwin directory itself, not /usr/include.
find_path(KWIN_INCLUDE_DIR
  NAMES effect/effect.h
  PATHS /usr/include/kwin /usr/local/include/kwin
)

find_path(KWIN_PARENT_INCLUDE_DIR
  NAMES kwin/effect/effect.h
  PATHS /usr/include /usr/local/include
)

find_library(KWIN_LIBRARY
  NAMES kwin
  PATHS /usr/lib /usr/lib64 /usr/lib/x86_64-linux-gnu
)

if(NOT KWIN_INCLUDE_DIR OR NOT KWIN_LIBRARY)
  message(FATAL_ERROR
    "KWin development files not found. Install the KWin development package "
    "or configure with -DTEXTPIK_BUILD_KWIN_EFFECT=OFF.")
endif()

message(STATUS "KWin include dir: ${KWIN_INCLUDE_DIR}")
message(STATUS "KWin library:     ${KWIN_LIBRARY}")

add_library(textpik-kwin-effect MODULE
  effect.cpp
  effect.h
  metadata.json
)

target_include_directories(textpik-kwin-effect
  PRIVATE
    ${KWIN_INCLUDE_DIR}
    ${TEXTPIK_KF6_INCLUDES}
)

target_link_libraries(textpik-kwin-effect
  PRIVATE
    ${KWIN_LIBRARY}
    ${TEXTPIK_KF6_LIBS}
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    Qt6::DBus
)

set_target_properties(textpik-kwin-effect PROPERTIES
  OUTPUT_NAME "textpik-placement"
  PREFIX ""
)

if(DEFINED TEXTPIK_KWIN_EFFECT_DESTINATION)
  install(TARGETS textpik-kwin-effect
    LIBRARY DESTINATION ${TEXTPIK_KWIN_EFFECT_DESTINATION})
endif()

# Loads the built effect the way KWin would (dlopen + resolve the factory) and
# instantiates it, so packaging and CI can assert ABI compatibility with the
# installed libkwin without restarting the compositor.
add_executable(textpik-verify-effect verify_effect.cpp)
target_link_libraries(textpik-verify-effect
  PRIVATE ${KWIN_LIBRARY} ${TEXTPIK_KF6_LIBS} Qt6::Core Qt6::Gui Qt6::Widgets Qt6::DBus
)
target_include_directories(textpik-verify-effect
  PRIVATE ${KWIN_INCLUDE_DIR} ${TEXTPIK_KF6_INCLUDES}
)
