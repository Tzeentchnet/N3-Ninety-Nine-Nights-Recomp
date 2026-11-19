#pragma once
#include <rex/ppc/context.h>

// Host-created callback contexts may start with csr=0. Guest rounding/flush
// settings are meaningful, but zero host exception masks must not reach MXCSR.
inline void InitializeCallbackFpState(PPCContext& context) {
  const auto guest_bits = context.fpscr.csr & rex::ppc::FPSCRRegister::kGuestMask;
  context.fpscr.InitHost();
  context.fpscr.RestoreGuestBits(guest_bits);
}
