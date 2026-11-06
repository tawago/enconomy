// AAudio (MMAP exclusive when granted) duplex for one PoP run. JNI for com.enconomy.pop.AAudioNative.
//
// Output: float mono, the callback writes play[i] at stream frame W0 + i (W0 = framesWritten at the first
// callback), zeros after the end. Input: int16 mono, the callback stores stream frame R0 + i at rec[i]
// (R0 = framesRead at the first callback). Indexing by the stream counters, not by a private counter, keeps
// the content on the device timeline across xruns. Timestamps (CLOCK_MONOTONIC) are polled from Kotlin.
#include <aaudio/AAudio.h>
#include <android/log.h>
#include <dlfcn.h>
#include <jni.h>
#include <time.h>

#include <atomic>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#define TAG "PopAAudio"
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN, TAG, __VA_ARGS__)

namespace {

struct Duplex {
    AAudioStream* out = nullptr;
    AAudioStream* in = nullptr;
    std::vector<float> play;
    std::vector<int16_t> rec;
    std::atomic<int64_t> w0{-1}, r0{-1};
    std::atomic<int64_t> outPos{0};  // content frames handed to the device (W - W0)
    std::atomic<int64_t> recPos{0};  // highest rec index written + 1
    std::atomic<int32_t> outErr{0}, inErr{0};
    std::atomic<int32_t> outCallbacks{0}, inCallbacks{0};
    std::atomic<int64_t> outMaxJump{0}, inMaxJump{0};  // largest gap between consecutive callbacks' stream counters
};

std::string g_err;

aaudio_data_callback_result_t outCb(AAudioStream* s, void* user, void* data, int32_t n) {
    auto* d = static_cast<Duplex*>(user);
    int64_t w = AAudioStream_getFramesWritten(s);
    int64_t w0 = d->w0.load(std::memory_order_relaxed);
    if (w0 < 0) {
        w0 = w;
        d->w0.store(w, std::memory_order_relaxed);
    } else {
        int64_t jump = w - w0 - d->outPos.load(std::memory_order_relaxed);
        if (jump > d->outMaxJump.load(std::memory_order_relaxed)) d->outMaxJump.store(jump, std::memory_order_relaxed);
    }
    auto* o = static_cast<float*>(data);
    int64_t i0 = w - w0;
    int64_t total = static_cast<int64_t>(d->play.size());
    for (int32_t k = 0; k < n; ++k) {
        int64_t i = i0 + k;
        o[k] = (i >= 0 && i < total) ? d->play[i] : 0.0f;
    }
    d->outPos.store(i0 + n, std::memory_order_release);
    d->outCallbacks.fetch_add(1, std::memory_order_relaxed);
    return AAUDIO_CALLBACK_RESULT_CONTINUE;
}

aaudio_data_callback_result_t inCb(AAudioStream* s, void* user, void* data, int32_t n) {
    auto* d = static_cast<Duplex*>(user);
    int64_t r = AAudioStream_getFramesRead(s);
    int64_t r0 = d->r0.load(std::memory_order_relaxed);
    if (r0 < 0) {
        r0 = r;
        d->r0.store(r, std::memory_order_relaxed);
    } else {
        int64_t jump = r - r0 - d->recPos.load(std::memory_order_relaxed);
        if (jump > d->inMaxJump.load(std::memory_order_relaxed)) d->inMaxJump.store(jump, std::memory_order_relaxed);
    }
    auto* x = static_cast<const int16_t*>(data);
    int64_t i0 = r - r0;
    int64_t cap = static_cast<int64_t>(d->rec.size());
    for (int32_t k = 0; k < n; ++k) {
        int64_t i = i0 + k;
        if (i >= 0 && i < cap) d->rec[i] = x[k];
    }
    int64_t end = i0 + n < cap ? i0 + n : cap;
    d->recPos.store(end, std::memory_order_release);
    d->inCallbacks.fetch_add(1, std::memory_order_relaxed);
    return AAUDIO_CALLBACK_RESULT_CONTINUE;
}

void outErrCb(AAudioStream*, void* user, aaudio_result_t e) { static_cast<Duplex*>(user)->outErr.store(e); }
void inErrCb(AAudioStream*, void* user, aaudio_result_t e) { static_cast<Duplex*>(user)->inErr.store(e); }

// AAudioStream_isMMapUsed is exported by libaaudio but not in the NDK headers. -1 = unknown.
int isMmap(AAudioStream* s) {
    using Fn = bool (*)(AAudioStream*);
    static Fn fn = reinterpret_cast<Fn>(dlsym(RTLD_DEFAULT, "AAudioStream_isMMapUsed"));
    if (!fn) {
        void* h = dlopen("libaaudio.so", RTLD_NOW);
        if (h) fn = reinterpret_cast<Fn>(dlsym(h, "AAudioStream_isMMapUsed"));
    }
    return fn ? (fn(s) ? 1 : 0) : -1;
}

bool openOne(Duplex* d, bool output, int sr, bool exclusive, int preset, AAudioStream** out) {
    AAudioStreamBuilder* b = nullptr;
    aaudio_result_t r = AAudio_createStreamBuilder(&b);
    if (r != AAUDIO_OK) {
        g_err = std::string("createStreamBuilder: ") + AAudio_convertResultToText(r);
        return false;
    }
    AAudioStreamBuilder_setDirection(b, output ? AAUDIO_DIRECTION_OUTPUT : AAUDIO_DIRECTION_INPUT);
    AAudioStreamBuilder_setSampleRate(b, sr);
    AAudioStreamBuilder_setChannelCount(b, 1);
    AAudioStreamBuilder_setFormat(b, output ? AAUDIO_FORMAT_PCM_FLOAT : AAUDIO_FORMAT_PCM_I16);
    AAudioStreamBuilder_setSharingMode(b, exclusive ? AAUDIO_SHARING_MODE_EXCLUSIVE : AAUDIO_SHARING_MODE_SHARED);
    AAudioStreamBuilder_setPerformanceMode(b, AAUDIO_PERFORMANCE_MODE_LOW_LATENCY);
    if (output) {
        AAudioStreamBuilder_setUsage(b, AAUDIO_USAGE_MEDIA);
        AAudioStreamBuilder_setContentType(b, AAUDIO_CONTENT_TYPE_SONIFICATION);
        AAudioStreamBuilder_setDataCallback(b, outCb, d);
        AAudioStreamBuilder_setErrorCallback(b, outErrCb, d);
    } else {
        AAudioStreamBuilder_setInputPreset(b, preset);
        AAudioStreamBuilder_setDataCallback(b, inCb, d);
        AAudioStreamBuilder_setErrorCallback(b, inErrCb, d);
    }
    r = AAudioStreamBuilder_openStream(b, out);
    AAudioStreamBuilder_delete(b);
    if (r != AAUDIO_OK) {
        g_err = std::string(output ? "open output: " : "open input: ") + AAudio_convertResultToText(r);
        *out = nullptr;
        return false;
    }
    int32_t got = AAudioStream_getSampleRate(*out);
    if (got != sr) {
        g_err = std::string(output ? "output" : "input") + " runs at " + std::to_string(got) + ", wanted " + std::to_string(sr);
        AAudioStream_close(*out);
        *out = nullptr;
        return false;
    }
    // Output: a few bursts of headroom against callback jitter (the timeline is timestamped, latency is free).
    if (output) {
        int32_t burst = AAudioStream_getFramesPerBurst(*out);
        if (burst > 0) AAudioStream_setBufferSizeInFrames(*out, 4 * burst);
    }
    return true;
}

void closeAll(Duplex* d) {
    if (d->out) {
        AAudioStream_requestStop(d->out);
        AAudioStream_close(d->out);
        d->out = nullptr;
    }
    if (d->in) {
        AAudioStream_requestStop(d->in);
        AAudioStream_close(d->in);
        d->in = nullptr;
    }
}

Duplex* H(jlong h) { return reinterpret_cast<Duplex*>(h); }

// Oboe's calculateLatencyMillis: output = frames queued ahead of the presented one, input = frames waiting.
double latencyMs(AAudioStream* s, bool output) {
    int64_t pos = 0, t = 0;
    if (AAudioStream_getTimestamp(s, CLOCK_MONOTONIC, &pos, &t) != AAUDIO_OK) return -1.0;
    timespec now{};
    clock_gettime(CLOCK_MONOTONIC, &now);
    int64_t nowNs = now.tv_sec * 1000000000LL + now.tv_nsec;
    double sr = AAudioStream_getSampleRate(s);
    if (output) {
        int64_t w = AAudioStream_getFramesWritten(s);
        double presentNs = t + (w - pos) * 1e9 / sr;
        return (presentNs - nowNs) / 1e6;
    }
    int64_t r = AAudioStream_getFramesRead(s);
    double appNs = t + (r - pos) * 1e9 / sr;
    return (nowNs - appNs) / 1e6;
}

}  // namespace

extern "C" {

JNIEXPORT jlong JNICALL Java_com_enconomy_pop_AAudioNative_open(JNIEnv* env, jclass, jint sr, jboolean exclusive, jint preset,
                                                                jfloatArray play, jint recFrames) {
    auto* d = new Duplex();
    if (play) {
        jsize n = env->GetArrayLength(play);
        d->play.resize(n);
        env->GetFloatArrayRegion(play, 0, n, d->play.data());
    }
    d->rec.assign(recFrames > 0 ? recFrames : 0, 0);
    if (!openOne(d, true, sr, exclusive, preset, &d->out) || !openOne(d, false, sr, exclusive, preset, &d->in)) {
        closeAll(d);
        delete d;
        return 0;
    }
    return reinterpret_cast<jlong>(d);
}

JNIEXPORT jstring JNICALL Java_com_enconomy_pop_AAudioNative_lastError(JNIEnv* env, jclass) {
    return env->NewStringUTF(g_err.c_str());
}

// [outSharing, inSharing, outMmap, inMmap, outBurst, inBurst, outBuf, inBuf, outCap, inCap, outPerf, inPerf,
//  inPreset, outFormat, inFormat]  sharing: 0 exclusive, 1 shared; mmap: 1/0/-1 unknown
JNIEXPORT jintArray JNICALL Java_com_enconomy_pop_AAudioNative_info(JNIEnv* env, jclass, jlong h) {
    Duplex* d = H(h);
    jint v[15] = {
        AAudioStream_getSharingMode(d->out), AAudioStream_getSharingMode(d->in),
        isMmap(d->out), isMmap(d->in),
        AAudioStream_getFramesPerBurst(d->out), AAudioStream_getFramesPerBurst(d->in),
        AAudioStream_getBufferSizeInFrames(d->out), AAudioStream_getBufferSizeInFrames(d->in),
        AAudioStream_getBufferCapacityInFrames(d->out), AAudioStream_getBufferCapacityInFrames(d->in),
        AAudioStream_getPerformanceMode(d->out), AAudioStream_getPerformanceMode(d->in),
        AAudioStream_getInputPreset(d->in),
        AAudioStream_getFormat(d->out), AAudioStream_getFormat(d->in),
    };
    jintArray a = env->NewIntArray(15);
    env->SetIntArrayRegion(a, 0, 15, v);
    return a;
}

JNIEXPORT jint JNICALL Java_com_enconomy_pop_AAudioNative_startIn(JNIEnv*, jclass, jlong h) {
    return AAudioStream_requestStart(H(h)->in);
}

JNIEXPORT jint JNICALL Java_com_enconomy_pop_AAudioNative_startOut(JNIEnv*, jclass, jlong h) {
    return AAudioStream_requestStart(H(h)->out);
}

JNIEXPORT void JNICALL Java_com_enconomy_pop_AAudioNative_stop(JNIEnv*, jclass, jlong h) {
    Duplex* d = H(h);
    if (d->out) AAudioStream_requestStop(d->out);
    if (d->in) AAudioStream_requestStop(d->in);
}

// Timestamp relative to the first callback's stream frame: [ok, framePosition - base, nanoTime].
// ok: 1 = read, 0 = not available yet (or before the first callback), < 0 = AAudio error.
JNIEXPORT jlongArray JNICALL Java_com_enconomy_pop_AAudioNative_timestamp(JNIEnv* env, jclass, jlong h, jboolean output) {
    Duplex* d = H(h);
    AAudioStream* s = output ? d->out : d->in;
    int64_t base = output ? d->w0.load() : d->r0.load();
    jlong v[3] = {0, 0, 0};
    if (base >= 0) {
        int64_t pos = 0, t = 0;
        aaudio_result_t r = AAudioStream_getTimestamp(s, CLOCK_MONOTONIC, &pos, &t);
        if (r == AAUDIO_OK) {
            v[0] = 1;
            v[1] = pos - base;
            v[2] = t;
        } else if (r != AAUDIO_ERROR_INVALID_STATE) {
            v[0] = r;
        }
    }
    jlongArray a = env->NewLongArray(3);
    env->SetLongArrayRegion(a, 0, 3, v);
    return a;
}

// [outPos, playFrames, recPos, recCapacity, w0, r0, outXruns, inXruns, outErr, inErr, outCallbacks, inCallbacks,
//  outMaxJump, inMaxJump]
JNIEXPORT jlongArray JNICALL Java_com_enconomy_pop_AAudioNative_status(JNIEnv* env, jclass, jlong h) {
    Duplex* d = H(h);
    jlong v[14] = {
        d->outPos.load(), static_cast<jlong>(d->play.size()), d->recPos.load(), static_cast<jlong>(d->rec.size()),
        d->w0.load(), d->r0.load(), AAudioStream_getXRunCount(d->out), AAudioStream_getXRunCount(d->in),
        d->outErr.load(), d->inErr.load(), d->outCallbacks.load(), d->inCallbacks.load(),
        d->outMaxJump.load(), d->inMaxJump.load(),
    };
    jlongArray a = env->NewLongArray(14);
    env->SetLongArrayRegion(a, 0, 14, v);
    return a;
}

// [outLatencyMs, inLatencyMs], -1 = no timestamp
JNIEXPORT jdoubleArray JNICALL Java_com_enconomy_pop_AAudioNative_latency(JNIEnv* env, jclass, jlong h) {
    Duplex* d = H(h);
    jdouble v[2] = {latencyMs(d->out, true), latencyMs(d->in, false)};
    jdoubleArray a = env->NewDoubleArray(2);
    env->SetDoubleArrayRegion(a, 0, 2, v);
    return a;
}

JNIEXPORT jshortArray JNICALL Java_com_enconomy_pop_AAudioNative_capture(JNIEnv* env, jclass, jlong h, jint start, jint n) {
    Duplex* d = H(h);
    if (start < 0 || n < 0 || static_cast<size_t>(start) + n > d->rec.size()) return nullptr;
    jshortArray a = env->NewShortArray(n);
    env->SetShortArrayRegion(a, 0, n, reinterpret_cast<const jshort*>(d->rec.data() + start));
    return a;
}

JNIEXPORT void JNICALL Java_com_enconomy_pop_AAudioNative_close(JNIEnv*, jclass, jlong h) {
    Duplex* d = H(h);
    closeAll(d);
    delete d;
}

}  // extern "C"
