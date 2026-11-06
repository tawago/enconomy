package dev.enconomy.rawrec;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.media.audiofx.AcousticEchoCanceler;
import android.media.audiofx.AutomaticGainControl;
import android.media.audiofx.AudioEffect;
import android.media.audiofx.NoiseSuppressor;
import android.os.Bundle;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.List;

/** Tone test recorder: same mic settings as the PoP app (AudioEngine.android.kt). 3 s wait, 20 s capture, plain WAV. */
public class Main extends Activity {
    static final int SR = 48000, SECONDS = 20, WAIT_S = 3;
    TextView status;
    Button go;
    volatile boolean busy;

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setGravity(Gravity.CENTER);
        l.setPadding(48, 48, 48, 48);
        status = new TextView(this);
        status.setTextSize(20);
        status.setText("Start the tone, then tap Record and let go of the phone.");
        go = new Button(this);
        go.setText("Record " + SECONDS + " s");
        go.setOnClickListener(v -> start());
        l.addView(status);
        l.addView(go);
        setContentView(l);
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
    }

    void say(String s) { runOnUiThread(() -> status.setText(s)); }

    void start() {
        if (busy) return;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
            return;
        }
        busy = true;
        go.setEnabled(false);
        new Thread(() -> {
            try {
                for (int i = WAIT_S; i > 0; i--) { say("Hands off. Starting in " + i); Thread.sleep(1000); }
                say(capture());
            } catch (Throwable t) {
                say("FAILED: " + t);
            }
            busy = false;
            runOnUiThread(() -> go.setEnabled(true));
        }).start();
    }

    String capture() throws Exception {
        AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
        boolean unp = "true".equals(am.getProperty(AudioManager.PROPERTY_SUPPORT_AUDIO_SOURCE_UNPROCESSED));
        int source = unp ? MediaRecorder.AudioSource.UNPROCESSED : MediaRecorder.AudioSource.VOICE_RECOGNITION;
        String srcName = unp ? "UNPROCESSED" : "VOICE_RECOGNITION";
        int min = AudioRecord.getMinBufferSize(SR, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord r = new AudioRecord.Builder()
                .setAudioSource(source)
                .setAudioFormat(new AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(SR).setChannelMask(AudioFormat.CHANNEL_IN_MONO).build())
                .setBufferSizeInBytes(Math.max(min, 2 * SR))
                .build();
        if (r.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException("AudioRecord not initialized");
        if (r.getSampleRate() != SR) throw new IllegalStateException("mic runs at " + r.getSampleRate());
        List<AudioEffect> fx = new ArrayList<>();
        int s = r.getAudioSessionId();
        try { if (AutomaticGainControl.isAvailable()) fx.add(AutomaticGainControl.create(s)); } catch (Throwable ignored) { }
        try { if (NoiseSuppressor.isAvailable()) fx.add(NoiseSuppressor.create(s)); } catch (Throwable ignored) { }
        try { if (AcousticEchoCanceler.isAvailable()) fx.add(AcousticEchoCanceler.create(s)); } catch (Throwable ignored) { }
        for (AudioEffect e : fx) if (e != null) try { e.setEnabled(false); } catch (Throwable ignored) { }

        short[] pcm = new short[SR * SECONDS];
        r.startRecording();
        int got = 0, peak = 0;
        while (got < pcm.length) {
            int n = r.read(pcm, got, Math.min(4800, pcm.length - got));
            if (n <= 0) throw new IllegalStateException("read returned " + n);
            for (int i = got; i < got + n; i++) peak = Math.max(peak, Math.abs((int) pcm[i]));
            got += n;
            say("Recording " + (got / SR) + " / " + SECONDS + " s, peak " + peak);
        }
        r.stop();
        r.release();
        for (AudioEffect e : fx) if (e != null) try { e.release(); } catch (Throwable ignored) { }

        File f = new File(getExternalFilesDir(null), "rec_" + System.currentTimeMillis() + ".wav");
        writeWav(f, pcm);
        new FileOutputStream(new File(f.getPath() + ".txt")).write(("source=" + srcName + " peak=" + peak + "\n").getBytes());
        return "Saved " + f.getName() + "\nsource " + srcName + ", peak " + peak;
    }

    static void writeWav(File f, short[] pcm) throws Exception {
        ByteBuffer b = ByteBuffer.allocate(44 + pcm.length * 2).order(ByteOrder.LITTLE_ENDIAN);
        b.put("RIFF".getBytes()).putInt(36 + pcm.length * 2).put("WAVEfmt ".getBytes()).putInt(16)
                .putShort((short) 1).putShort((short) 1).putInt(SR).putInt(SR * 2).putShort((short) 2).putShort((short) 16)
                .put("data".getBytes()).putInt(pcm.length * 2);
        for (short v : pcm) b.putShort(v);
        try (FileOutputStream o = new FileOutputStream(f)) { o.write(b.array()); }
    }
}
