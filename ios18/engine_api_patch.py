#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Make the engine's audio and video code run on iOS 18.

Upstream calls a few APIs that exist only from iOS 26/27. Each call keeps its
new form where the system has it and gets the older equivalent elsewhere:
  - AVAudioEngine's error-returning calls -> the older raising calls, caught;
  - the iOS 27 session notifications -> AVAudioSessionInterruptionNotification;
  - two optional VideoToolbox calls -> skipped before the iOS that has them.
Every replacement must match exactly, or the script fails.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])


class Source:
    def __init__(self, relative: str):
        self.path = root / relative
        self.name = relative
        self.text = self.path.read_text()

    def replace(self, old: str, new: str, count: int = 1) -> None:
        found = self.text.count(old)
        if found != count:
            raise SystemExit(f"{self.name}: expected {count} of {old[:60]!r}, found {found}")
        self.text = self.text.replace(old, new)

    def wrap(self, start: str, end: str, before: str, after: str) -> None:
        if self.text.count(start) != 1:
            raise SystemExit(f"{self.name}: block start not found: {start[:60]!r}")
        first = self.text.index(start)
        last = self.text.index(end, first)
        self.text = self.text[:first] + before + self.text[first:last] + after + self.text[last:]

    def after_last_include(self, block: str) -> None:
        lines = self.text.split("\n")
        last = max(i for i, line in enumerate(lines)
                   if line.startswith("#include") or line.startswith("#import"))
        lines.insert(last + 1, block)
        self.text = "\n".join(lines)

    def save(self) -> None:
        self.path.write_text(self.text)


HELPERS = '''
// iOS 18 compatibility: the error-returning calls are iOS 27; before it the
// older calls raise, which is caught and reported as the same failure.
namespace {
[[maybe_unused]] BOOL umlInstallTap(AVAudioNode* node, AVAudioNodeBus bus,
    AVAudioFrameCount size, AVAudioFormat* format, NSError** error,
    AVAudioNodeTapBlock block)
{
    if (@available(iOS 27.0, macOS 27.0, *)) {
        return [node installTapOnBus:bus bufferSize:size format:format
                               error:error block:block];
    }
    @try {
        [node installTapOnBus:bus bufferSize:size format:format block:block];
        return YES;
    } @catch (NSException*) {
        return NO;
    }
}
[[maybe_unused]] BOOL umlConnect(AVAudioEngine* engine, AVAudioNode* from,
    AVAudioNode* to, AVAudioFormat* format, NSError** error)
{
    if (@available(iOS 27.0, macOS 27.0, *))
        return [engine connect:from to:to format:format error:error];
    @try {
        [engine connect:from to:to format:format];
        return YES;
    } @catch (NSException*) {
        return NO;
    }
}
[[maybe_unused]] BOOL umlPlay(AVAudioPlayerNode* player, NSError** error)
{
    if (@available(iOS 27.0, macOS 27.0, *))
        return [player playAndReturnError:error];
    @try {
        [player play];
        return YES;
    } @catch (NSException*) {
        return NO;
    }
}
}  // namespace
'''

# --- microphone ---------------------------------------------------------------
mic = Source("darwin/device/audio/apple_microphone_input.mm")
mic.after_last_include(HELPERS)
mic.replace('''            const BOOL tapped = [input
                installTapOnBus:0
                     bufferSize:static_cast<AVAudioFrameCount>(
                                    inputFormat.sampleRate * tapSeconds)
                         format:inputFormat
                          error:&tapError
                          block:^(AVAudioPCMBuffer* buffer, AVAudioTime*) {''',
            '''            const BOOL tapped = umlInstallTap(input, 0,
                static_cast<AVAudioFrameCount>(
                    inputFormat.sampleRate * tapSeconds),
                inputFormat, &tapError,
                ^(AVAudioPCMBuffer* buffer, AVAudioTime*) {''')
mic.replace('''                               }
                             }];
            if (!tapped) {''', '''                               }
                             });
            if (!tapped) {''')
mic.wrap("        deactivationObserver_ = [NSNotificationCenter.defaultCenter\n", "#endif\n",
         "        if (@available(iOS 27.0, *)) {\n",
         '''        } else {
            // Before iOS 27: one interruption notification, begun and ended.
            deactivationObserver_ = [NSNotificationCenter.defaultCenter
                addObserverForName:AVAudioSessionInterruptionNotification
                            object:[AVAudioSession sharedInstance]
                             queue:nil
                        usingBlock:^(NSNotification* notification) {
                          const auto capture = weak.lock();
                          if (!capture)
                              return;
                          NSNumber* type = notification.userInfo[
                              AVAudioSessionInterruptionTypeKey];
                          if (type.unsignedIntegerValue ==
                              AVAudioSessionInterruptionTypeBegan)
                              capture->interrupt();
                        }];
            resumptionObserver_ = [NSNotificationCenter.defaultCenter
                addObserverForName:AVAudioSessionInterruptionNotification
                            object:[AVAudioSession sharedInstance]
                             queue:nil
                        usingBlock:^(NSNotification* notification) {
                          const auto capture = weak.lock();
                          if (!capture)
                              return;
                          NSNumber* type = notification.userInfo[
                              AVAudioSessionInterruptionTypeKey];
                          if (type.unsignedIntegerValue !=
                              AVAudioSessionInterruptionTypeEnded)
                              return;
                          NSNumber* options = notification.userInfo[
                              AVAudioSessionInterruptionOptionKey];
                          capture->resume((options.unsignedIntegerValue &
                              AVAudioSessionInterruptionOptionShouldResume) != 0);
                        }];
        }
''')
mic.save()

# --- playback -----------------------------------------------------------------
sink = Source("darwin/device/audio/apple_playback_sink.mm")
sink.after_last_include(HELPERS)
sink.replace('''            if (![engine_ connect:player_
                               to:engine_.mainMixerNode
                           format:format_
                            error:&connectError]) {''',
             '''            if (!umlConnect(engine_, player_, engine_.mainMixerNode,
                            format_, &connectError)) {''')
sink.replace("[player_ playAndReturnError:&error]", "umlPlay(player_, &error)", 3)
sink.replace("[player playAndReturnError:&error]", "umlPlay(player, &error)")
sink.wrap("        deactivationObserver_ = [[NSNotificationCenter defaultCenter]\n", "#endif\n",
          "        if (@available(iOS 27.0, *)) {\n",
          '''        } else {
            // Before iOS 27: one interruption notification, begun and ended.
            deactivationObserver_ = [[NSNotificationCenter defaultCenter]
                addObserverForName:AVAudioSessionInterruptionNotification
                            object:[AVAudioSession sharedInstance]
                             queue:nil
                        usingBlock:^(NSNotification* notification) {
                          const auto flags = weakNotifications.lock();
                          if (!flags)
                              return;
                          NSNumber* type = notification.userInfo[
                              AVAudioSessionInterruptionTypeKey];
                          if (type.unsignedIntegerValue ==
                              AVAudioSessionInterruptionTypeBegan)
                              flags->signal(flags->interruptionBegan);
                        }];
            resumptionObserver_ = [[NSNotificationCenter defaultCenter]
                addObserverForName:AVAudioSessionInterruptionNotification
                            object:[AVAudioSession sharedInstance]
                             queue:nil
                        usingBlock:^(NSNotification* notification) {
                          const auto flags = weakNotifications.lock();
                          if (!flags)
                              return;
                          NSNumber* type = notification.userInfo[
                              AVAudioSessionInterruptionTypeKey];
                          if (type.unsignedIntegerValue !=
                              AVAudioSessionInterruptionTypeEnded)
                              return;
                          NSNumber* options = notification.userInfo[
                              AVAudioSessionInterruptionOptionKey];
                          if ((options.unsignedIntegerValue &
                               AVAudioSessionInterruptionOptionShouldResume) != 0) {
                              flags->resumeRecommended.store(
                                  true, std::memory_order_release);
                          }
                          flags->signal(flags->interruptionEnded);
                        }];
        }
''')
sink.save()

# --- video --------------------------------------------------------------------
decoder = Source("darwin/platform/apple/video_decoder.mm")
decoder.replace(
    "        VTRegisterSupplementalVideoDecoderIfAvailable(kCMVideoCodecType_VP9);\n",
    "        if (@available(iOS 26.2, *))\n"
    "            VTRegisterSupplementalVideoDecoderIfAvailable(kCMVideoCodecType_VP9);\n")
decoder.save()

encoder = Source("darwin/platform/apple/video_encoder.mm")
encoder.replace(
    '''            if (s.bufferBits && s.bitrate)
                (void)apply(session, UML_KEY(VBVBufferDuration), @(double(s.bufferBits) / double(s.bitrate)), false);
''',
    '''            if (@available(iOS 26.0, *)) {
                if (s.bufferBits && s.bitrate)
                    (void)apply(session, UML_KEY(VBVBufferDuration), @(double(s.bufferBits) / double(s.bitrate)), false);
            }
''')
encoder.save()
print("audio and video code given iOS 18 equivalents")
