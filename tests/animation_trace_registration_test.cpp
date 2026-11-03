#include <rex/ppc.h>
#include <array>
#include <iostream>

extern "C" void sub_82093BE8(PPCContext&, uint8_t*);
extern "C" void sub_82080158(PPCContext&, uint8_t*);
extern "C" void sub_82252BD8(PPCContext&, uint8_t*);
extern "C" void sub_82298FF0(PPCContext&, uint8_t*);
extern "C" void sub_82249628(PPCContext&, uint8_t*);
extern "C" void sub_822733B8(PPCContext&, uint8_t*);
extern "C" void sub_82273000(PPCContext&, uint8_t*);
extern "C" void sub_82272AF0(PPCContext&, uint8_t*);
extern "C" void sub_82272F58(PPCContext&, uint8_t*);
extern "C" void sub_82272C40(PPCContext&, uint8_t*);
extern "C" void sub_8224E6F0(PPCContext&, uint8_t*);
extern "C" void sub_82298E78(PPCContext&, uint8_t*);
extern "C" void sub_8224E9B0(PPCContext&, uint8_t*);
extern "C" void sub_8229CF30(PPCContext&, uint8_t*);
extern "C" void sub_8224AC98(PPCContext&, uint8_t*);
extern "C" void sub_82251D38(PPCContext&, uint8_t*);
extern "C" void sub_8224E0B8(PPCContext&, uint8_t*);
extern "C" void sub_82249FB0(PPCContext&, uint8_t*);
extern "C" void sub_820A4648(PPCContext&, uint8_t*);
extern "C" void sub_820AF768(PPCContext&, uint8_t*);
extern "C" void sub_8208D878(PPCContext&, uint8_t*);
extern "C" void sub_820AAFB0(PPCContext&, uint8_t*);
extern "C" void sub_820A2968(PPCContext&, uint8_t*);
extern "C" void sub_8217AD08(PPCContext&, uint8_t*);
extern "C" void sub_8229CA98(PPCContext&, uint8_t*);
extern "C" void sub_8210BF78(PPCContext&, uint8_t*);
extern "C" void sub_8210CB78(PPCContext&, uint8_t*);
extern "C" void sub_8210BE98(PPCContext&, uint8_t*);
extern "C" void sub_8210CAB8(PPCContext&, uint8_t*);
extern "C" void sub_8210C728(PPCContext&, uint8_t*);
extern "C" void sub_8210CFE8(PPCContext&, uint8_t*);
extern "C" void sub_82097868(PPCContext&, uint8_t*);
extern "C" void sub_82097958(PPCContext&, uint8_t*);
extern "C" void sub_82097D00(PPCContext&, uint8_t*);
extern "C" void sub_820927C0(PPCContext&, uint8_t*);
extern "C" void sub_8209BE30(PPCContext&, uint8_t*);
extern "C" void sub_82097D90(PPCContext&, uint8_t*);
extern "C" void sub_8212ACA8(PPCContext&, uint8_t*);
extern PPCFuncMapping PPCFuncMappings[];

int main() {
  struct Entry { uint32_t guest; PPCFunc* host; };
  constexpr std::array<Entry, 38> entries{{
      {0x82093be8, sub_82093BE8}, {0x82080158, sub_82080158},
      {0x82252bd8, sub_82252BD8}, {0x82298ff0, sub_82298FF0},
      {0x82249628, sub_82249628},
      {0x822733b8, sub_822733B8}, {0x82273000, sub_82273000},
      {0x82272af0, sub_82272AF0}, {0x82272f58, sub_82272F58},
      {0x82272c40, sub_82272C40}, {0x8224e6f0, sub_8224E6F0},
      {0x82298e78, sub_82298E78}, {0x8224e9b0, sub_8224E9B0},
      {0x8229cf30, sub_8229CF30}, {0x8224ac98, sub_8224AC98},
      {0x82251d38, sub_82251D38}, {0x8224e0b8, sub_8224E0B8},
      {0x82249fb0, sub_82249FB0}, {0x820a4648, sub_820A4648},
      {0x820af768, sub_820AF768}, {0x8208d878, sub_8208D878},
      {0x820aafb0, sub_820AAFB0}, {0x820a2968, sub_820A2968},
      {0x8217ad08, sub_8217AD08}, {0x8229ca98, sub_8229CA98},
      {0x8210bf78, sub_8210BF78}, {0x8210cb78, sub_8210CB78},
      {0x8210be98, sub_8210BE98}, {0x8210cab8, sub_8210CAB8},
      {0x8210c728, sub_8210C728}, {0x8210cfe8, sub_8210CFE8},
      {0x82097868, sub_82097868}, {0x82097958, sub_82097958},
      {0x82097d00, sub_82097D00}, {0x820927c0, sub_820927C0},
      {0x8209be30, sub_8209BE30}, {0x82097d90, sub_82097D90},
      {0x8212aca8, sub_8212ACA8}}};
  for (const auto& entry : entries) {
    bool found = false;
    for (auto* mapping = PPCFuncMappings; mapping->guest; ++mapping)
      if (mapping->guest == entry.guest) found = mapping->host == entry.host;
    if (!found) {
      std::cerr << "animation trace hook is missing from indirect registration\n";
      return 1;
    }
  }
  std::cout << "all thirty-eight retained-call hooks registered\n";
  return 0;
}
