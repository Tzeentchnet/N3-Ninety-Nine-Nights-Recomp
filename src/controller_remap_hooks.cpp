#include "controller_remap.h"
#include "controller_settings.h"
#include "guest_memory_address.h"

#include <rex/ppc.h>
#include <rex/xam/input.h>

namespace {

n3::input::ControllerRemap ConfiguredRemap() {
  using namespace n3::input;
  auto& settings = N3_CONTROLLER_SETTINGS();
  ControllerRemap remap;
  remap.a = ParseDigitalSource(settings.button_a.Get()).value_or(DigitalSource::kA);
  remap.b = ParseDigitalSource(settings.button_b.Get()).value_or(DigitalSource::kB);
  remap.x = ParseDigitalSource(settings.button_x.Get()).value_or(DigitalSource::kX);
  remap.y = ParseDigitalSource(settings.button_y.Get()).value_or(DigitalSource::kY);
  remap.left_shoulder =
      ParseDigitalSource(settings.left_shoulder.Get())
          .value_or(DigitalSource::kLeftShoulder);
  remap.right_shoulder =
      ParseDigitalSource(settings.right_shoulder.Get())
          .value_or(DigitalSource::kRightShoulder);
  remap.left_thumb = ParseDigitalSource(settings.left_thumb.Get())
                         .value_or(DigitalSource::kLeftThumb);
  remap.right_thumb = ParseDigitalSource(settings.right_thumb.Get())
                          .value_or(DigitalSource::kRightThumb);
  remap.dpad_up = ParseDigitalSource(settings.dpad_up.Get())
                      .value_or(DigitalSource::kDPadUp);
  remap.dpad_down = ParseDigitalSource(settings.dpad_down.Get())
                        .value_or(DigitalSource::kDPadDown);
  remap.dpad_left = ParseDigitalSource(settings.dpad_left.Get())
                        .value_or(DigitalSource::kDPadLeft);
  remap.dpad_right = ParseDigitalSource(settings.dpad_right.Get())
                         .value_or(DigitalSource::kDPadRight);
  remap.back =
      ParseDigitalSource(settings.back.Get()).value_or(DigitalSource::kBack);
  remap.start =
      ParseDigitalSource(settings.start.Get()).value_or(DigitalSource::kStart);
  remap.guide =
      ParseDigitalSource(settings.guide.Get()).value_or(DigitalSource::kGuide);
  remap.left_trigger = ParseTriggerSource(settings.left_trigger.Get())
                           .value_or(TriggerSource::kLeft);
  remap.right_trigger = ParseTriggerSource(settings.right_trigger.Get())
                            .value_or(TriggerSource::kRight);
  remap.left_stick = ParseStickSource(settings.left_stick.Get())
                         .value_or(StickSource::kLeft);
  remap.right_stick = ParseStickSource(settings.right_stick.Get())
                          .value_or(StickSource::kRight);
  remap.invert_left_x = settings.invert_left_x.Get();
  remap.invert_left_y = settings.invert_left_y.Get();
  remap.invert_right_x = settings.invert_right_x.Get();
  remap.invert_right_y = settings.invert_right_y.Get();
  return remap;
}

void RemapGuestState(rex::xam::X_INPUT_STATE& guest) {
  const n3::input::ControllerState input{
      .buttons = guest.gamepad.buttons,
      .left_trigger = guest.gamepad.left_trigger,
      .right_trigger = guest.gamepad.right_trigger,
      .left_x = guest.gamepad.thumb_lx,
      .left_y = guest.gamepad.thumb_ly,
      .right_x = guest.gamepad.thumb_rx,
      .right_y = guest.gamepad.thumb_ry,
  };
  const auto output =
      n3::input::ApplyControllerRemap(input, ConfiguredRemap());
  guest.gamepad.buttons = output.buttons;
  guest.gamepad.left_trigger = output.left_trigger;
  guest.gamepad.right_trigger = output.right_trigger;
  guest.gamepad.thumb_lx = output.left_x;
  guest.gamepad.thumb_ly = output.left_y;
  guest.gamepad.thumb_rx = output.right_x;
  guest.gamepad.thumb_ry = output.right_y;
}

}  // namespace

extern "C" void __imp__XamInputGetState(PPCContext& ctx, uint8_t* base);
extern "C" void sub_8252E5F0(PPCContext& ctx, uint8_t* base) {
  const uint32_t output_address = ctx.r4.u32;
  ctx.r5.u64 = ctx.r4.u64;
  ctx.r4.s64 = 0;
  __imp__XamInputGetState(ctx, base);
  if (ctx.r3.u32 != 0 || output_address == 0 ||
      !n3::guest::FitsLinearGuestRange(
          output_address, sizeof(rex::xam::X_INPUT_STATE))) {
    return;
  }
  auto* state = reinterpret_cast<rex::xam::X_INPUT_STATE*>(
      n3::guest::GuestHostAddress(base, output_address));
  RemapGuestState(*state);
}
