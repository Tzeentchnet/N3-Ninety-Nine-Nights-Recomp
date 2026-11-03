#pragma once

#include <filesystem>

void InitializeAnimationTrace(const std::filesystem::path& game_root,
                              const std::filesystem::path& user_root);
void ShutdownAnimationTrace();

#ifdef N3_ANIMATION_TRACE_TEST
#include "animation_trace_model.h"
void ConfigureAnimationTraceForTest(n3::animation_trace::Filter filter, bool quaternion = false,
                                    bool signal = false, bool attachment = false);
const n3::animation_trace::Trace& AnimationTraceSnapshotForTest();
void StopAnimationTraceAdmissionForTest();
bool DrainAnimationTraceForTest(uint32_t timeout_ms);
void PauseAnimationTraceInvalidOutputForTest(bool pause);
bool AnimationTraceInvalidOutputPausedForTest();
void SetAnimationTraceOutputsForTest(const std::filesystem::path& prefix);
void SetAttachmentHashBytesForTest(uint64_t bytes);
bool AnimationTraceReadForTest(uint8_t* base, uint32_t address, void* output, uint32_t size);
#endif
