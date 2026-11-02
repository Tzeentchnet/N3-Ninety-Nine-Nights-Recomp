"""Apply N3's required integration fixes to ReXGlue-generated CMake."""

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = ROOT / "generated" / "rexglue.cmake"

OFFICIAL_OUTPUTS = """# library rexglue_setup_target() builds. The stamp comes first: the DEPFILE
# names it.
add_custom_command(
    OUTPUT "${CMAKE_CURRENT_SOURCE_DIR}/generated/default/codegen.build.stamp"
           ${REXGLUE_ENTRYPOINT_GENERATED_SOURCES}
    COMMAND $<TARGET_FILE:rex::rexglue> codegen ${CMAKE_CURRENT_SOURCE_DIR}/n3_manifest.toml"""

N3_OUTPUTS = '''# library rexglue_setup_target() builds. The stamp comes first: the DEPFILE
# names it. The headers are outputs too: sources and the PCH depend on them
# through compiler depfiles, so Ninja must not consider them current before
# codegen has had an opportunity to rewrite them.
add_custom_command(
    OUTPUT "${CMAKE_CURRENT_SOURCE_DIR}/generated/default/codegen.build.stamp"
           ${REXGLUE_ENTRYPOINT_GENERATED_SOURCES}
           "${CMAKE_CURRENT_SOURCE_DIR}/generated/default/n3_pch.h"
           "${CMAKE_CURRENT_SOURCE_DIR}/generated/default/n3_init.h"
    # Route incremental builds through the same pin/XEX checks and post-processing
    # as an explicit tools/codegen.ps1 invocation.
    COMMAND "${N3_PWSH_EXECUTABLE}" -NoProfile -File
            "${CMAKE_CURRENT_SOURCE_DIR}/tools/codegen.ps1"
            -Python "${Python3_EXECUTABLE}"'''


def patch_text(text):
    if N3_OUTPUTS in text:
        if text.count(N3_OUTPUTS) != 1 or OFFICIAL_OUTPUTS in text:
            raise ValueError("Generated CMake contains conflicting N3 integration blocks")
        return text
    if text.count(OFFICIAL_OUTPUTS) != 1:
        raise ValueError("Generated CMake no longer matches the pinned ReXGlue template")
    return text.replace(OFFICIAL_OUTPUTS, N3_OUTPUTS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    path = args.path.resolve()
    original = path.read_text(encoding="utf-8")
    patched = patch_text(original)
    if patched == original:
        print(f"Generated CMake integration is up to date: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(patched, encoding="utf-8", newline="\n")
    temporary.replace(path)
    print(f"Applied N3 generated-CMake integration: {path}")


if __name__ == "__main__":
    main()
