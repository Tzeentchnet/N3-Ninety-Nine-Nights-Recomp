#include "text_language.h"

#include <rex/ppc.h>
#include <rex/settings_registry.h>

void N3GetTextLanguage(PPCRegister& result) {
  const auto setting = REX_SETTINGS().Find("n3.text_language");
  const auto language = setting ? (*setting)->GetText() : "english";
  result.u64 = n3::text::LanguageCode(language);
}
