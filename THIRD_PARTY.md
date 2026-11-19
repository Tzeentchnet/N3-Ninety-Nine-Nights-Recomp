# Third-party notices

Project-authored source and documentation are licensed under the BSD 3-Clause
License in [`LICENSE`](LICENSE). The components and adapted work identified
below retain their respective copyright notices and license terms.

ReXGlue supplies the downloaded code generator and the source-built modular
runtime, platform services, and Xenos drivers. It is derived in part from
Xenia. N3 pins stable ReXGlue v0.11.0 at:

- https://github.com/rexglue/rexglue-sdk/tree/a3e1d82678ca20d68d4837a8e9ee4652ff073745
- https://github.com/rexglue/rexglue-sdk/blob/a3e1d82678ca20d68d4837a8e9ee4652ff073745/LICENSE
- https://github.com/xenia-project/xenia

The project's disc extractor implements the XDVDFS structure documented by
Xenia's disc image reader. ReXGlue's own dependency notices remain applicable to
downloaded libraries and any future packaged binary distribution.

N3 applies two narrowly scoped renderer corrections under
`tools/rexglue/patches/`: the raw physical GPU view remains writable instead of
inheriting title-alias allocation or page-protection state, and Vulkan
presentation uses swapchain-image semaphores with an idle barrier during
swapchain retirement.
The same patch set also backports ReXGlue's later source-pinning approach for
Vulkan-Headers and Vulkan Memory Allocator. No separate temporal FidelityFX
runtime or DLL is included, and stable ReXGlue 0.11 does not contain the earlier
FSR1 presentation-effect path.

Vulkan-Headers is pinned at
`9fbc2a782ee3f8a4db64e7d991e23da75e893f44`; Vulkan Memory Allocator is
pinned at `0f1a757da579831283413295cc7f3b47eb521c77`. Their upstream notices
and licences are preserved in the corresponding-source archive and packaged
license tree.

Bootstrap downloads official LLVM, CMake, Ninja, and Microsoft development tools.
Their respective licences apply. The pinned portable Microsoft-tool downloader
is by mmozeiko: https://gist.github.com/mmozeiko/7f3162ec2988e81e56d5c4e22cde9977.

LostOdysseyRecomp and UnleashedRecomp were consulted as architectural references;
their source is not included here. The GPL Donelys N3 fork was consulted for
language/voice behavior, and pgr4-native for renderer architecture; none of
their code, branding, or artwork is included. Original Ninety-Nine Nights
material is not included in the tracked project or release asset files.

The offline loose-file mod stager and its tests were adapted from the user's
MIT-licensed N3-ReGPU project at commit
`c03c26e7b80851a391ffb5f19bbc499c0f84fb5c`. Its immutable-extraction,
deterministic-load-order, copy-on-override, and path-safety model was retained
while defaults and launch integration were adapted for this repository. The
complete notice is in `LICENSES/N3-ReGPU.txt`. No N3-ReGPU generated game code,
runtime, renderer, or original game data is included.

## Binary releases

Current development builds the complete matched modular ReXGlue 0.11 runtime
from the exact stable source plus the tracked patches. D3D12 is the Windows
default; Vulkan and null drivers are also supplied. Third-party components
include SDL3, FFmpeg, libmspack, spdlog, simde, xxHash, toml++, Dear ImGui,
CLI11, Tracy, glslang, Vulkan-Headers, Vulkan Memory Allocator, and small
vendored utility libraries. Their notices, including notices embedded in source
headers, are preserved under `licenses/` in the package. This software is based
in part on the work of the Independent JPEG Group.

FFmpeg and libmspack contain LGPL components. Each release supplies a separate
corresponding-source archive containing the SDK, every submodule, the extra
pinned Vulkan dependencies, N3's patches and integration scripts, original
build scripts, and license texts. The SDK's CMake files specify the codec
sources and configuration. `SOURCE-MANIFEST.json` records upstream URLs, commit
IDs, and source archive checksums. Compatible rebuilt modular `rex*.dll`
libraries may replace the supplied DLLs. Reverse engineering for debugging
modifications to LGPL components is permitted. The N3 project source is
available at the corresponding release tag; building translated game code
requires a matching executable from a disc.

Application-local Microsoft Visual C++ release x64 runtime DLLs are included from
the official Microsoft redistributable archive. Microsoft retains their rights;
see the package notice and [Microsoft's redistribution documentation](https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files).
