// Read-only macOS Now Playing and default-output snapshot.
#import <Foundation/Foundation.h>
#import <CoreAudio/CoreAudio.h>
#import <objc/message.h>

static id call0(id object, NSString *name) {
    SEL selector = NSSelectorFromString(name);
    if (!object || ![object respondsToSelector:selector]) return nil;
    return ((id (*)(id, SEL))objc_msgSend)(object, selector);
}

static NSString *deviceString(AudioDeviceID device, AudioObjectPropertySelector selector) {
    AudioObjectPropertyAddress property = {selector, kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain};
    CFStringRef value = NULL;
    UInt32 size = sizeof(value);
    if (AudioObjectGetPropertyData(device, &property, 0, NULL, &size, &value) != noErr || !value) return @"";
    return CFBridgingRelease(value);
}

static NSDictionary *snapshot(void) {
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    AudioObjectPropertyAddress property = {kAudioHardwarePropertyDefaultOutputDevice,
        kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain};
    AudioDeviceID device = kAudioObjectUnknown;
    UInt32 size = sizeof(device);
    if (AudioObjectGetPropertyData(kAudioObjectSystemObject, &property, 0, NULL, &size, &device) == noErr && device) {
        result[@"output_name"] = deviceString(device, kAudioObjectPropertyName);
        result[@"output_uid"] = deviceString(device, kAudioDevicePropertyDeviceUID);
    }
    NSBundle *bundle = [NSBundle bundleWithPath:@"/System/Library/PrivateFrameworks/MediaRemote.framework"];
    if (![bundle load]) {
        result[@"error"] = @"MediaRemote framework unavailable";
        return result;
    }
    Class request = NSClassFromString(@"MRNowPlayingRequest");
    if (!request || ![request respondsToSelector:NSSelectorFromString(@"localNowPlayingItem")]) {
        result[@"error"] = @"Now Playing snapshot API unavailable";
        return result;
    }
    id item = call0(request, @"localNowPlayingItem");
    NSDictionary *info = call0(item, @"nowPlayingInfo");
    if (![info isKindOfClass:[NSDictionary class]]) info = @{};
    NSDictionary *keys = @{
        @"title": @"kMRMediaRemoteNowPlayingInfoTitle",
        @"artist": @"kMRMediaRemoteNowPlayingInfoArtist",
        @"album": @"kMRMediaRemoteNowPlayingInfoAlbum",
        @"duration": @"kMRMediaRemoteNowPlayingInfoDuration",
        @"elapsed": @"kMRMediaRemoteNowPlayingInfoElapsedTime",
        @"rate": @"kMRMediaRemoteNowPlayingInfoPlaybackRate",
        @"timestamp": @"kMRMediaRemoteNowPlayingInfoTimestamp"
    };
    for (NSString *key in keys) {
        id value = info[keys[key]];
        if ([value isKindOfClass:[NSString class]]) result[key] = [value substringToIndex:MIN([value length], 256)];
        else if ([value isKindOfClass:[NSNumber class]]) result[key] = value;
        else if ([value isKindOfClass:[NSDate class]]) result[key] = @([value timeIntervalSince1970]);
    }
    id player = call0(request, @"localNowPlayingPlayerPath");
    id client = call0(player, @"client");
    id app = call0(client, @"bundleIdentifier");
    if ([app isKindOfClass:[NSString class]]) result[@"app"] = app;
    result[@"has_item"] = @([info count] > 0);
    return result;
}

__attribute__((visibility("default"))) void bm83_now_playing(void) {
    @autoreleasepool {
        @try {
            NSError *error = nil;
            NSData *data = [NSJSONSerialization dataWithJSONObject:snapshot() options:0 error:&error];
            if (!data) { fputs("{\"error\":\"snapshot serialization failed\"}\n", stdout); exit(1); }
            fwrite(data.bytes, 1, data.length, stdout);
            fputc('\n', stdout);
            fflush(stdout);
            exit(0);
        } @catch (NSException *exception) {
            fputs("{\"error\":\"Now Playing API unavailable\"}\n", stdout);
            exit(1);
        }
    }
}
