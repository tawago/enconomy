# WVP Chromium patch

The main way to try WVP is the extension in stock Chrome, see `../wvp/README.md`. This patch adds two things over that:

- **No install.** The extension ships beside the binary and loads by itself.
- **The browser's own real-click check.** `wvpPrivate.approve` consumes the tab's user activation in the browser process and reads the tab's real origin. In stock Chrome that check is only `login.js`, which is weaker.

The rules are in `SPEC.md`.

The native prompt is off. The patch still holds it: `askUser` and the popup's WVP text are unused. The extension no longer asks for it, so the patch didn't change when the prompt went away.

The patch touches 9 files: 271 lines added, 7 removed. `wvp_private/` holds readable copies of its 4 new files. You don't copy them in, the patch adds them.

It was built and run on Linux x64 only. A full build took about 1 h 40 min on 32 vCPUs and needs about 43 GB of disk.

```sh
# 1. Get the tag. Install depot_tools first.
mkdir chromium && cd chromium
git init src && git -C src remote add origin https://chromium.googlesource.com/chromium/src.git
git -C src fetch --depth 1 --no-tags origin refs/tags/157.0.8103.38:refs/tags/157.0.8103.38
git -C src checkout 157.0.8103.38
cat > .gclient <<'G'
solutions = [{"name": "src", "url": "https://chromium.googlesource.com/chromium/src.git", "managed": False, "custom_deps": {}, "custom_vars": {}}]
G
gclient sync --nohooks --no-history
sudo src/build/install-build-deps.sh --no-prompt --no-arm --no-nacl --no-chromeos-fonts --no-syms
gclient runhooks
cd src

# 2. Apply.
git apply /path/to/browser/wvp.patch

# 3. Configure and build.
mkdir -p out/Demo && cp /path/to/browser/args.gn out/Demo/args.gn
gn gen out/Demo
autoninja -C out/Demo chrome chrome_sandbox

# 4. Put the extension beside the binary. No folder means no extension.
WVP_THIRD_PARTY=/path/to/third_party /path/to/wvp/extension/build.sh "$PWD/out/Demo/wvp_extension"
```

Ubuntu 24.04 restricts user namespaces, so Chromium stops with "No usable sandbox". Install the helper:

```sh
sudo install -o root -g root -m 4755 out/Demo/chrome_sandbox /usr/local/sbin/chrome-devel-sandbox
export CHROME_DEVEL_SANDBOX=/usr/local/sbin/chrome-devel-sandbox
```

Run the demo from `wvp/`, once its servers have what they need (`wvp/README.md`):

```sh
WVP_COMPONENT=1 WVP_CHROME=/path/to/src/out/Demo/chrome WVP_THIRD_PARTY=/path/to/third_party node demo/try-it.mjs
```

`--smoke` wasn't tried on this build.
