package com.gamemine.tickgate.ipc;

import com.gamemine.tickgate.TickGate;
import com.gamemine.tickgate.core.TickGateFrameCapture;
import com.gamemine.tickgate.core.TickGateState;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import net.minecraft.server.MinecraftServer;

public final class TickGateIpcServer {

    private static volatile TickGateIpcServer running;

    public static synchronized void startIfEnabled(boolean enabled, String host, int port) {
        if (!enabled) {
            TickGate.LOGGER.info("TickGate IPC disabled by config");
            return;
        }
        if (running != null) return;
        TickGateIpcServer s = new TickGateIpcServer(host, port);
        if (s.bind()) {
            running = s;
            s.startAcceptLoop();
        }
    }

    public static synchronized void stop() {
        TickGateIpcServer s = running;
        running = null;
        if (s != null) s.close();
    }

    private final String host;
    private final int port;
    private final AtomicBoolean stopped = new AtomicBoolean(false);
    private ServerSocket server;
    private Thread acceptThread;

    private TickGateIpcServer(String host, int port) {
        this.host = host;
        this.port = port;
    }

    private boolean bind() {
        try {
            server = new ServerSocket();
            server.setReuseAddress(true);
            server.bind(new InetSocketAddress(InetAddress.getByName(host), port));
            TickGate.LOGGER.info("TickGate IPC listening on {}:{}", host, port);
            return true;
        } catch (IOException e) {
            TickGate.LOGGER.error("TickGate IPC failed to bind {}:{} — {}", host, port, e.toString());
            server = null;
            return false;
        }
    }

    private void startAcceptLoop() {
        acceptThread = new Thread(this::acceptLoop, "TickGate-IPC-Accept");
        acceptThread.setDaemon(true);
        acceptThread.start();
    }

    private void acceptLoop() {
        while (!stopped.get()) {
            Socket sock;
            try {
                sock = server.accept();
            } catch (IOException e) {
                if (!stopped.get()) {
                    TickGate.LOGGER.warn("TickGate IPC accept failed: {}", e.toString());
                }
                return;
            }
            Thread t = new Thread(() -> handle(sock),
                "TickGate-IPC-Client-" + sock.getRemoteSocketAddress());
            t.setDaemon(true);
            t.start();
        }
    }

    private void handle(Socket sock) {
        try (sock;
             BufferedReader in = new BufferedReader(
                 new InputStreamReader(sock.getInputStream(), StandardCharsets.UTF_8));
             PrintWriter out = new PrintWriter(
                 new java.io.OutputStreamWriter(sock.getOutputStream(), StandardCharsets.UTF_8), true)) {

            InetAddress remote = sock.getInetAddress();
            if (!remote.isLoopbackAddress()) {
                out.println(err("remote not allowed"));
                return;
            }

            sock.setTcpNoDelay(true);
            String line;
            while (!stopped.get() && (line = in.readLine()) != null) {
                String reply = dispatch(line.trim());
                if (reply == null) break;
                out.println(reply);
            }
        } catch (IOException e) {
            TickGate.LOGGER.debug("TickGate IPC client closed: {}", e.toString());
        }
    }

    private String dispatch(String line) {
        if (line.isEmpty()) return ok();

        String[] parts = line.split("\\s+", 2);
        String verb = parts[0].toLowerCase();
        String arg = parts.length > 1 ? parts[1].trim() : "";

        TickGateState state = TickGateState.get();
        long start = System.nanoTime();
        state.recordCommand(verb);
        try {
            switch (verb) {
                case "ping":
                    return "{\"ok\":true,\"pong\":true}";
                case "ready":
                    return "{\"ok\":true,\"worldReady\":" + state.isWorldReady() + "}";
                case "wait_ready":
                    state.awaitWorldReady();
                    return ok();
                case "pause":
                    state.pause();
                    return ok();
                case "resume":
                    state.resume();
                    return ok();
                case "step": {
                    long n = parsePositiveLong(arg);
                    state.validateStepBatch(n);
                    state.addPendingTicks(n);
                    return ok();
                }
                case "step_wait":
                case "step_wait_server": {
                    long n = parsePositiveLong(arg);
                    state.validateStepBatch(n);
                    state.addPendingTicks(n);
                    state.awaitServerTicks(n);
                    return ok();
                }
                case "step_wait_client": {
                    long n = parsePositiveLong(arg);
                    state.awaitRenderFrames(n);
                    return ok();
                }
                case "step_wait_dual": {
                    long n = parsePositiveLong(arg);
                    state.validateStepBatch(n);
                    state.addPendingTicks(n);
                    state.awaitServerThenRender(n, 1L);
                    return ok();
                }
                case "observe_wait": {
                    long[] sr = parseTwoPositiveLongs(arg);
                    state.awaitServerThenRender(sr[0], sr[1]);
                    return ok();
                }
                case "observe_ready": {
                    long renderFrames = parseOptionalPositiveLong(arg, 1L);
                    state.awaitWorldReady();
                    state.pause();
                    state.awaitRenderFrames(renderFrames);
                    return ok();
                }
                case "observe_image": {
                    parseOptionalPositiveLong(arg, 1L);
                    state.awaitWorldReady();
                    state.pause();
                    long previousFrame = state.getCompletedRenderFrames();
                    TickGateFrameCapture.get().requestCapture();
                    TickGateFrameCapture.CapturedFrame frame = TickGateFrameCapture.get().awaitCaptureAfter(previousFrame, 10_000L);
                    if (!frame.ok()) return err(frame.error());
                    return image(frame);
                }
                case "advance_wait": {
                    long[] nr = parseAdvanceArgs(arg);
                    state.awaitWorldReady();
                    state.advanceExactly(nr[0]);
                    state.awaitRenderFrames(nr[1]);
                    return ok();
                }
                case "advance_image": {
                    long[] nr = parseAdvanceArgs(arg);
                    state.awaitWorldReady();
                    state.pause();
                    long previousFrame = state.getCompletedRenderFrames();
                    TickGateFrameCapture.get().requestCapture();
                    state.advanceExactly(nr[0]);
                    state.awaitRenderFrames(nr[1]);
                    TickGateFrameCapture.CapturedFrame frame = TickGateFrameCapture.get().awaitCaptureAfter(previousFrame, 10_000L);
                    if (!frame.ok()) return err(frame.error());
                    return image(frame);
                }
                case "step_observe": {
                    long[] nr = parseStepObserveArgs(arg);
                    long n = nr[0];
                    long renderFrames = nr[1] >= 0 ? nr[1] : state.nextStepObserveRenderFrames();
                    state.validateStepBatch(n);
                    state.addPendingTicks(n);
                    state.awaitServerThenRender(n, renderFrames);
                    return ok();
                }
                case "set_render_cadence": {
                    int cadence = Integer.parseInt(arg);
                    if (cadence < 1) return err("render cadence must be >= 1");
                    state.setRenderCadence(cadence);
                    return ok();
                }
                case "set_max_step_batch": {
                    long batch = Long.parseLong(arg);
                    if (batch < 1) return err("max step batch must be >= 1");
                    state.setMaxStepBatch(batch);
                    return ok();
                }
                case "stats":
                    return stats();
                case "status":
                    return ok();
                case "rate": {
                    int hz = Integer.parseInt(arg);
                    if (hz < 1 || hz > 1000) return err("hz out of range");
                    applyTickRate(hz);
                    return ok();
                }
                case "render_once":
                    state.requestRenderOnce();
                    return ok();
                case "client_pause":
                    state.setClientPaused(true);
                    return ok();
                case "client_resume":
                    state.setClientPaused(false);
                    return ok();
                case "quit":
                case "exit":
                case "close":
                    return null;
                default:
                    state.recordError();
                    return err("unknown verb: " + verb);
            }
        } catch (NumberFormatException nfe) {
            state.recordError();
            return err("bad number: " + arg);
        } catch (IllegalArgumentException iae) {
            state.recordError();
            return err(iae.getMessage());
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            state.recordInterrupted();
            state.recordError();
            return err("interrupted");
        } finally {
            state.recordCommandLatencyNanos(System.nanoTime() - start);
        }
    }

    private static long parsePositiveLong(String arg) {
        long n = Long.parseLong(arg);
        if (n <= 0) throw new IllegalArgumentException("n must be > 0");
        return n;
    }

    private static long[] parseTwoPositiveLongs(String arg) {
        String[] p = arg.split("\\s+");
        if (p.length != 2) throw new IllegalArgumentException("expected: <serverTicks> <renderFrames>");
        long s = Long.parseLong(p[0]);
        long r = Long.parseLong(p[1]);
        if (s <= 0 || r <= 0) throw new IllegalArgumentException("serverTicks and renderFrames must be > 0");
        return new long[]{s, r};
    }

    private static long[] parseStepObserveArgs(String arg) {
        if (arg.isEmpty()) throw new IllegalArgumentException("expected: <ticks> [renderFrames]");
        String[] p = arg.split("\\s+");
        if (p.length == 1) {
            long n = Long.parseLong(p[0]);
            if (n <= 0) throw new IllegalArgumentException("ticks must be > 0");
            return new long[]{n, -1L};
        }
        if (p.length == 2) {
            long n = Long.parseLong(p[0]);
            long r = Long.parseLong(p[1]);
            if (n <= 0 || r < 0) throw new IllegalArgumentException("ticks must be > 0 and renderFrames must be >= 0");
            return new long[]{n, r};
        }
        throw new IllegalArgumentException("expected: <ticks> [renderFrames]");
    }

    private static long parseOptionalPositiveLong(String arg, long defaultValue) {
        if (arg.isEmpty()) return defaultValue;
        long n = Long.parseLong(arg);
        if (n <= 0) throw new IllegalArgumentException("n must be > 0");
        return n;
    }

    private static long[] parseAdvanceArgs(String arg) {
        if (arg.isEmpty()) throw new IllegalArgumentException("expected: <ticks> [renderFrames]");
        String[] p = arg.split("\\s+");
        if (p.length == 1) {
            long n = Long.parseLong(p[0]);
            if (n <= 0) throw new IllegalArgumentException("ticks must be > 0");
            return new long[]{n, 1L};
        }
        if (p.length == 2) {
            long n = Long.parseLong(p[0]);
            long r = Long.parseLong(p[1]);
            if (n <= 0 || r < 0) throw new IllegalArgumentException("ticks must be > 0 and renderFrames must be >= 0");
            return new long[]{n, r};
        }
        throw new IllegalArgumentException("expected: <ticks> [renderFrames]");
    }

    private static void applyTickRate(int hz) {
        TickGateState state = TickGateState.get();
        state.setTickRate(hz);
        MinecraftServer server = TickGate.getCurrentServer();
        if (server != null) {
            server.execute(() -> server.tickRateManager().setTickRate((float) hz));
        }
    }

    private static String ok() {
        TickGateState s = TickGateState.get();
        long serverTicks = s.getCompletedServerTicks();
        long renderFrames = s.getCompletedRenderFrames();
        return "{\"ok\":true,"
            + "\"paused\":" + s.isPaused() + ","
            + "\"pendingTicks\":" + s.getPendingTicks() + ","
            + "\"completedServerTicks\":" + serverTicks + ","
            + "\"completedRenderFrames\":" + renderFrames + ","
            + "\"serverTick\":" + serverTicks + ","
            + "\"renderFrame\":" + renderFrames + ","
            + "\"observationFrame\":" + renderFrames + ","
            + "\"tickRate\":" + s.getTickRate() + ","
            + "\"clientPaused\":" + s.isClientPaused() + ","
            + "\"renderCadence\":" + s.getRenderCadence() + ","
            + "\"maxStepBatch\":" + s.getMaxStepBatch() + ","
            + "\"worldReady\":" + s.isWorldReady()
            + "}";
    }

    private static String stats() {
        TickGateState s = TickGateState.get();
        long cmds = s.getTotalCommands();
        long latency = s.getTotalCommandLatencyNanos();
        long avg = cmds == 0 ? 0 : latency / cmds;
        StringBuilder verbs = new StringBuilder();
        boolean first = true;
        for (Map.Entry<String, Long> e : s.getVerbCountsSnapshot().entrySet()) {
            if (!first) verbs.append(',');
            first = false;
            verbs.append('"').append(e.getKey().replace("\"", "\\\"")).append('"')
                .append(':').append(e.getValue());
        }
        return "{\"ok\":true,"
            + "\"commands\":" + cmds + ","
            + "\"errors\":" + s.getTotalErrors() + ","
            + "\"interrupted\":" + s.getTotalInterrupted() + ","
            + "\"totalCommandLatencyNanos\":" + latency + ","
            + "\"avgCommandLatencyNanos\":" + avg + ","
            + "\"totalServerWaitNanos\":" + s.getTotalServerWaitNanos() + ","
            + "\"totalRenderWaitNanos\":" + s.getTotalRenderWaitNanos() + ","
            + "\"verbs\":{" + verbs + "}}";
    }

    private static String image(TickGateFrameCapture.CapturedFrame frame) {
        TickGateState s = TickGateState.get();
        long serverTicks = s.getCompletedServerTicks();
        return "{\"ok\":true,"
            + "\"imageEncoding\":\"png_base64\"," 
            + "\"width\":" + frame.width() + ","
            + "\"height\":" + frame.height() + ","
            + "\"completedServerTicks\":" + serverTicks + ","
            + "\"completedRenderFrames\":" + s.getCompletedRenderFrames() + ","
            + "\"serverTick\":" + serverTicks + ","
            + "\"renderFrame\":" + frame.renderFrame() + ","
            + "\"observationFrame\":" + frame.renderFrame() + ","
            + "\"image\":\"" + frame.pngBase64() + "\"}";
    }

    private static String err(String msg) {
        return "{\"ok\":false,\"error\":\"" + msg.replace("\"", "\\\"") + "\"}";
    }

    private void close() {
        stopped.set(true);
        try {
            if (server != null) server.close();
        } catch (IOException ignored) {
        }
        if (acceptThread != null) acceptThread.interrupt();
        TickGate.LOGGER.info("TickGate IPC stopped");
    }
}
