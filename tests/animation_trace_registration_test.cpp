#include <rex/ppc.h>
#include <array>
#include <iostream>

extern "C" void sub_82093BE8(PPCContext&, uint8_t*);
extern "C" void sub_82080158(PPCContext&, uint8_t*);
extern "C" void sub_82252BD8(PPCContext&, uint8_t*);
extern "C" void sub_82298FF0(PPCContext&, uint8_t*);
extern "C" void sub_82249628(PPCContext&, uint8_t*);
extern PPCFuncMapping PPCFuncMappings[];

int main() {
  struct Entry { uint32_t guest; PPCFunc* host; };
  constexpr std::array<Entry, 5> entries{{
      {0x82093be8, sub_82093BE8}, {0x82080158, sub_82080158},
      {0x82252bd8, sub_82252BD8}, {0x82298ff0, sub_82298FF0},
      {0x82249628, sub_82249628}}};
  for (const auto& entry : entries) {
    bool found = false;
    for (auto* mapping = PPCFuncMappings; mapping->guest; ++mapping)
      if (mapping->guest == entry.guest) found = mapping->host == entry.host;
    if (!found) {
      std::cerr << "animation trace hook is missing from indirect registration\n";
      return 1;
    }
  }
  std::cout << "all five retained-call hooks registered\n";
  return 0;
}
