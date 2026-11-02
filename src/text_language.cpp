#include "text_language.h"

#include <rex/cvar.h>
#include <rex/ppc.h>

REXCVAR_DEFINE_STRING(n3_text_language, "english", "N3/Language",
                      "Language of PAL text and fonts (restart required)")
    .allowed({"english", "german", "french", "spanish", "italian"})
    .lifecycle(rex::cvar::Lifecycle::kRequiresRestart);

void N3GetTextLanguage(PPCRegister& result) {
  result.u64 = n3::text::LanguageCode(REXCVAR_GET(n3_text_language));
}
