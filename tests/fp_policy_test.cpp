#include "fp_policy.h"
#include <cstdio>

int main() {
  using Platform = rex::ppc::FPSCRPlatform;
  const auto saved_host = Platform::GetCSR();
  const auto guest_mask = rex::ppc::FPSCRRegister::kGuestMask;
  // Cover a fresh host callback plus each guest rounding mode with FTZ/DAZ.
  for (uint32_t mode = 0; mode < 5; ++mode) {
    PPCContext context{};
    context.fpscr.csr = mode == 0 ? 0 :
        static_cast<uint32_t>(Platform::kGuestToHost[mode - 1] | Platform::kFlushMask);
    const auto guest = context.fpscr.csr & guest_mask;
    InitializeCallbackFpState(context);
    const auto host = Platform::GetCSR();
#if defined(__x86_64__) || defined(_M_X64)
    const bool masks_correct = (host & Platform::kExceptionMask) == Platform::kExceptionMask;
#else
    const bool masks_correct = (host & Platform::kExceptionMask) == 0;
#endif
    if (!masks_correct || (host & guest_mask) != guest || context.fpscr.csr != host) {
      Platform::SetCSR(saved_host);
      std::fputs("Callback FP masks or guest controls are incorrect\n", stderr);
      return 1;
    }
  }
  Platform::SetCSR(saved_host);
  std::puts("Callback FP policy preserves guest controls and masks host exceptions");
}
