#include "runtime_fixes.h"
#include "fp_policy.h"

#include <rex/ppc.h>

extern "C" void __imp__sub_8253A590(PPCContext& context, uint8_t* base);
extern "C" void sub_8253A590(PPCContext& context, uint8_t* base) {
  InitializeCallbackFpState(context);
  __imp__sub_8253A590(context, base);
}
