These patches apply title-independent ReIGlue fixes to the pinned ReXGlue SDK
source before N3 builds its Xenos D3D12 plugin.

Source: https://github.com/FH1-ReImagined/ReIGlue
Base: bd833a2ab69d305f99ddf57418fc38ffec8af93d

- 0008: e1cce0608df6e0a890e14de23dd4756ae793e9d0
  Recheck texture memory validity before installing a watch.
- 0031: 9e7cd2ccf3be2ee29f7b1d0a606a3a0898377664
  Avoid allocation and the shared-memory lock when requested pages are valid.
- 0408: 3fcab351300f6e727529a36c303a28bdc133bd14
  Check both D3D12 fence HRESULTs before waiting.

ReIGlue is BSD 3-Clause licensed. See LICENSES/ReIGlue.txt.
