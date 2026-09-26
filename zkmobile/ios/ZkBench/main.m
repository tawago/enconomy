// Throwaway iOS harness: prove a Noir circuit with Barretenberg's C "bbapi" on device.
// Inputs (msgpack requests made on the laptop by prep.py) are bundled in inputs/ or copied to Documents/.
// Env: ZK_CIRCUIT (phone | phone_opt, default phone), HARDWARE_CONCURRENCY (bb threads).
// Writes Documents/log.txt (fsync per line, survives jetsam) and Documents/<circuit>.resp.msgpack.
#import <UIKit/UIKit.h>
#include <mach/mach.h>
#include <os/proc.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sys/time.h>

extern void bbapi(const uint8_t *in, size_t in_len, uint8_t **out, size_t *out_len);

static FILE *g_log;
static NSString *g_docs;
static _Atomic uint64_t g_peak_sampled;
static _Atomic int g_done;
static UILabel *g_label;

static double now_s(void) {
    struct timeval tv; gettimeofday(&tv, NULL); return tv.tv_sec + tv.tv_usec / 1e6;
}
static uint64_t footprint(uint64_t *peak) {
    task_vm_info_data_t vi; mach_msg_type_number_t n = TASK_VM_INFO_COUNT;
    if (task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&vi, &n) != KERN_SUCCESS) return 0;
    if (peak) *peak = vi.ledger_phys_footprint_peak;
    return vi.phys_footprint;
}
static void L(const char *fmt, ...) {
    char buf[1024]; va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof buf, fmt, ap); va_end(ap);
    uint64_t pk = 0; uint64_t fp = footprint(&pk);
    char line[1200];
    snprintf(line, sizeof line, "[%.3f] fp=%.1fMB peak=%.1fMB sampled=%.1fMB avail=%.1fMB | %s\n", now_s(),
             fp / 1048576.0, pk / 1048576.0, atomic_load(&g_peak_sampled) / 1048576.0,
             os_proc_available_memory() / 1048576.0, buf);
    fputs(line, stderr);
    if (g_log) { fputs(line, g_log); fflush(g_log); fsync(fileno(g_log)); }
    NSString *s = [NSString stringWithUTF8String:buf];
    dispatch_async(dispatch_get_main_queue(), ^{ g_label.text = [g_label.text stringByAppendingFormat:@"%@\n", s]; });
}
static void *sampler(void *arg) {
    (void)arg;
    uint64_t last_log = 0;
    while (!atomic_load(&g_done)) {
        uint64_t fp = footprint(NULL);
        if (fp > atomic_load(&g_peak_sampled)) atomic_store(&g_peak_sampled, fp);
        if (fp > last_log + 100 * 1048576ull) { last_log = fp; L("mem step"); }
        usleep(20000);
    }
    return NULL;
}
static NSData *load(NSString *name) {
    NSString *p = [g_docs stringByAppendingPathComponent:name];
    if (![[NSFileManager defaultManager] fileExistsAtPath:p])
        p = [[[NSBundle mainBundle] resourcePath] stringByAppendingPathComponent:[@"inputs" stringByAppendingPathComponent:name]];
    NSError *e = nil;
    NSData *d = [NSData dataWithContentsOfFile:p options:NSDataReadingMappedAlways error:&e];
    if (!d) L("load %s FAILED: %s", name.UTF8String, e.description.UTF8String);
    return d;
}
static int call(const char *what, NSData *req, NSData **resp_out) {
    uint8_t *out = NULL; size_t out_len = 0;
    L("%s: bbapi start (req %.1f MB)", what, req.length / 1048576.0);
    double t0 = now_s();
    bbapi(req.bytes, req.length, &out, &out_len);
    double dt = now_s() - t0;
    // response = [name, {...}]; fixarray(2) then str name
    const char *name = "?"; char nb[64] = {0};
    if (out_len > 3 && out[0] == 0x92) {
        size_t l = 0, off = 0;
        if ((out[1] & 0xe0) == 0xa0) { l = out[1] & 0x1f; off = 2; } else if (out[1] == 0xd9) { l = out[2]; off = 3; }
        if (l && l < sizeof nb) { memcpy(nb, out + off, l); name = nb; }
    }
    L("%s: bbapi done in %.3f s, resp %zu B, type %s", what, dt, out_len, name);
    if (strstr(name, "Error")) L("%s: ERROR body: %.*s", what, (int)(out_len < 900 ? out_len : 900), (const char *)out);
    if (resp_out) *resp_out = [NSData dataWithBytes:out length:out_len];
    free(out);
    return strstr(name, "Error") ? 1 : 0;
}
static void *run(void *arg) {
    (void)arg;
    @autoreleasepool {
        const char *c = getenv("ZK_CIRCUIT"); NSString *circuit = c ? @(c) : @"phone";
        const char *th = getenv("HARDWARE_CONCURRENCY");
        L("start circuit=%s threads=%s cores=%lu ram=%.0fMB", circuit.UTF8String, th ? th : "default",
          (unsigned long)[NSProcessInfo processInfo].activeProcessorCount,
          [NSProcessInfo processInfo].physicalMemory / 1048576.0);
        double T0 = now_s();
        NSData *srs = load(@"srs.msgpack");
        if (!srs || call("srs", srs, NULL)) goto end;
        srs = nil;
        NSData *req = load([circuit stringByAppendingString:@".req.msgpack"]);
        if (!req) goto end;
        NSData *resp = nil;
        double t0 = now_s();
        int err = call("prove", req, &resp);
        double t1 = now_s();
        req = nil;
        if (!err) {
            NSString *op = [g_docs stringByAppendingPathComponent:[circuit stringByAppendingString:@".resp.msgpack"]];
            [resp writeToFile:op atomically:YES];
        }
        uint64_t pk = 0; footprint(&pk);
        L("RESULT circuit=%s ok=%d prove_s=%.3f total_s=%.3f peak_ledger_MB=%.1f peak_sampled_MB=%.1f", circuit.UTF8String,
          !err, t1 - t0, t1 - T0, pk / 1048576.0, atomic_load(&g_peak_sampled) / 1048576.0);
    }
end:
    atomic_store(&g_done, 1);
    L("end");
    return NULL;
}

@interface App : UIResponder <UIApplicationDelegate>
@property(strong) UIWindow *window;
@end
@implementation App
- (BOOL)application:(UIApplication *)a didFinishLaunchingWithOptions:(NSDictionary *)o {
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *vc = [UIViewController new];
    g_label = [[UILabel alloc] initWithFrame:CGRectInset(UIScreen.mainScreen.bounds, 8, 40)];
    g_label.numberOfLines = 0; g_label.font = [UIFont monospacedSystemFontOfSize:10 weight:UIFontWeightRegular];
    g_label.text = @"";
    vc.view.backgroundColor = UIColor.whiteColor; g_label.textColor = UIColor.blackColor;
    [vc.view addSubview:g_label];
    self.window.rootViewController = vc; [self.window makeKeyAndVisible];
    [UIApplication sharedApplication].idleTimerDisabled = YES;

    g_docs = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
    g_log = fopen([g_docs stringByAppendingPathComponent:@"log.txt"].UTF8String, "a");
    L("---- launch; os_proc_available_memory at start = %.1f MB", os_proc_available_memory() / 1048576.0);
    pthread_t t; pthread_attr_t at; pthread_attr_init(&at);
    pthread_create(&t, NULL, sampler, NULL);
    pthread_attr_setstacksize(&at, 64 << 20);
    pthread_create(&t, &at, run, NULL);
    return YES;
}
@end

int main(int argc, char *argv[]) {
    @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass([App class])); }
}
