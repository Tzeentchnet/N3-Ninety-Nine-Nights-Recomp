These patches apply title-independent renderer fixes to the pinned ReXGlue SDK
source before N3 builds its runtime and Xenos D3D12 plugin.

Base: bd833a2ab69d305f99ddf57418fc38ffec8af93d

ReIGlue source: https://github.com/FH1-ReImagined/ReIGlue

- 0008: e1cce0608df6e0a890e14de23dd4756ae793e9d0
  Recheck texture memory validity before installing a watch.
- 0031: 9e7cd2ccf3be2ee29f7b1d0a606a3a0898377664
  Avoid allocation and the shared-memory lock when requested pages are valid.
- 0408: 3fcab351300f6e727529a36c303a28bdc133bd14
  Check both D3D12 fence HRESULTs before waiting.

ReIGlue is BSD 3-Clause licensed. See LICENSES/ReIGlue.txt.

ReXGlue source: https://github.com/rexglue/rexglue-sdk

- 1001: 0d5178ccb8122e37548af5417434ddde51463d6b
  Write the SV_SampleIndex semantic for sample-rate memexport pixel shaders.
- 1002: 30eaa07332a5857c7c3a6489329d2b4fbcac494a
  Correct extreme-FXAA initialization, bindless sampler layout lookup and IDs,
  3D tiled-depth alignment, and depth render-target encoding comparison.

The ReXGlue fixes retain its BSD 3-Clause terms.
