package com.gamemine.tickgate.core;

import java.io.IOException;
import java.util.Base64;

import com.gamemine.tickgate.TickGate;

import com.mojang.blaze3d.platform.NativeImage;

import net.minecraft.client.Minecraft;
import net.minecraft.client.Screenshot;

public final class TickGateFrameCapture {

    private static final TickGateFrameCapture INSTANCE = new TickGateFrameCapture();

    public static TickGateFrameCapture get() {
        return INSTANCE;
    }

    private final Object lock = new Object();

    private boolean captureRequested = false;
    private long lastCaptureFrame = -1L;
    private int lastWidth = 0;
    private int lastHeight = 0;
    private String lastPngBase64 = "";
    private String lastError = "";

    private TickGateFrameCapture() {}

    public void requestCapture() {
        synchronized (lock) {
            captureRequested = true;
            lastError = "";
        }
    }

    public void captureIfRequested(long renderFrame) {
        synchronized (lock) {
            if (!captureRequested) return;
            captureRequested = false;
        }

        try {
            Minecraft minecraft = Minecraft.getInstance();
            if (minecraft == null || minecraft.getMainRenderTarget() == null) {
                fail(renderFrame, "minecraft render target is not ready");
                return;
            }
            try (NativeImage image = Screenshot.takeScreenshot(minecraft.getMainRenderTarget())) {
                byte[] png = image.asByteArray();
                synchronized (lock) {
                    lastCaptureFrame = renderFrame;
                    lastWidth = image.getWidth();
                    lastHeight = image.getHeight();
                    lastPngBase64 = Base64.getEncoder().encodeToString(png);
                    lastError = "";
                    lock.notifyAll();
                }
            }
        } catch (IOException | RuntimeException error) {
            TickGate.LOGGER.warn("TickGate frame capture failed: {}", error.toString());
            fail(renderFrame, error.toString());
        }
    }

    public CapturedFrame awaitCaptureAfter(long previousFrame, long timeoutMillis) throws InterruptedException {
        long deadline = System.currentTimeMillis() + timeoutMillis;
        synchronized (lock) {
            while (lastCaptureFrame <= previousFrame && lastError.isEmpty()) {
                long remaining = deadline - System.currentTimeMillis();
                if (remaining <= 0L) {
                    return CapturedFrame.error("timed out waiting for captured frame");
                }
                lock.wait(remaining);
            }
            if (!lastError.isEmpty()) {
                return CapturedFrame.error(lastError);
            }
            return new CapturedFrame(true, lastCaptureFrame, lastWidth, lastHeight, lastPngBase64, "");
        }
    }

    private void fail(long renderFrame, String message) {
        synchronized (lock) {
            lastCaptureFrame = renderFrame;
            lastError = message;
            lock.notifyAll();
        }
    }

    public record CapturedFrame(boolean ok, long renderFrame, int width, int height, String pngBase64, String error) {
        public static CapturedFrame error(String message) {
            return new CapturedFrame(false, -1L, 0, 0, "", message);
        }
    }
}