package com.gamemine.tickgate.core;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.Condition;
import java.util.concurrent.locks.ReentrantLock;

public final class TickGateState {

    private static final TickGateState INSTANCE = new TickGateState();

    public static TickGateState get() {
        return INSTANCE;
    }

    private final ReentrantLock lock = new ReentrantLock();
    private final Condition budgetChanged = lock.newCondition();
    private final Condition serverBarrierChanged = lock.newCondition();
    private final Condition renderBarrierChanged = lock.newCondition();
    private final Condition readyChanged = lock.newCondition();

    private boolean paused = false;
    private long pendingTicks = 0L;

    private long completedServerTicks = 0L;
    private long completedRenderFrames = 0L;
    private boolean worldReady = false;

    private final AtomicBoolean clientPaused = new AtomicBoolean(false);
    private final AtomicBoolean renderOnce = new AtomicBoolean(false);

    private volatile int tickRate = 20;
    private volatile int renderCadence = 1;
    private volatile long maxStepBatch = 1_000_000L;
    private long stepObserveCounter = 0L;

    private final AtomicLong totalCommands = new AtomicLong(0L);
    private final AtomicLong totalErrors = new AtomicLong(0L);
    private final AtomicLong totalInterrupted = new AtomicLong(0L);
    private final AtomicLong totalCommandLatencyNanos = new AtomicLong(0L);
    private final AtomicLong totalServerWaitNanos = new AtomicLong(0L);
    private final AtomicLong totalRenderWaitNanos = new AtomicLong(0L);
    private final ConcurrentHashMap<String, AtomicLong> verbCounts = new ConcurrentHashMap<>();

    private TickGateState() {}

    public void pause() {
        lock.lock();
        try {
            paused = true;
            budgetChanged.signalAll();
        } finally {
            lock.unlock();
        }
    }

    public void resume() {
        lock.lock();
        try {
            paused = false;
            pendingTicks = 0L;
            budgetChanged.signalAll();
        } finally {
            lock.unlock();
        }
    }

    public void addPendingTicks(long n) {
        if (n <= 0) return;
        lock.lock();
        try {
            paused = true;
            pendingTicks += n;
            budgetChanged.signalAll();
        } finally {
            lock.unlock();
        }
    }

    public void validateStepBatch(long n) {
        if (n <= 0) throw new IllegalArgumentException("n must be > 0");
        long cap = maxStepBatch;
        if (n > cap) {
            throw new IllegalArgumentException("n exceeds maxStepBatch=" + cap);
        }
    }

    public long nextStepObserveRenderFrames() {
        lock.lock();
        try {
            stepObserveCounter++;
            return (stepObserveCounter % Math.max(1, renderCadence) == 0) ? 1L : 0L;
        } finally {
            lock.unlock();
        }
    }

    public void awaitTickPermission() throws InterruptedException {
        lock.lock();
        try {
            while (paused && pendingTicks == 0L) {
                budgetChanged.await();
            }
            if (paused && pendingTicks > 0L) {
                pendingTicks--;
            }
        } finally {
            lock.unlock();
        }
    }

    public void recordServerTickCompleted() {
        lock.lock();
        try {
            completedServerTicks++;
            serverBarrierChanged.signalAll();
            budgetChanged.signalAll();
        } finally {
            lock.unlock();
        }
    }

    public void recordRenderFrameCompleted() {
        lock.lock();
        try {
            completedRenderFrames++;
            renderBarrierChanged.signalAll();
        } finally {
            lock.unlock();
        }
    }

    public void awaitServerTicks(long n) throws InterruptedException {
        if (n <= 0) return;
        long start = System.nanoTime();
        lock.lock();
        try {
            long target = completedServerTicks + n;
            while (completedServerTicks < target) {
                serverBarrierChanged.await();
            }
        } finally {
            lock.unlock();
            totalServerWaitNanos.addAndGet(System.nanoTime() - start);
        }
    }

    public void advanceExactly(long n) throws InterruptedException {
        validateStepBatch(n);
        long start = 0L;
        boolean waiting = false;
        lock.lock();
        try {
            if (pendingTicks != 0L) {
                throw new IllegalArgumentException("pendingTicks must be 0 before advanceExactly");
            }
            paused = true;
            long target = completedServerTicks + n;
            pendingTicks = n;
            start = System.nanoTime();
            waiting = true;
            budgetChanged.signalAll();
            while (completedServerTicks < target) {
                serverBarrierChanged.await();
            }
        } finally {
            lock.unlock();
            if (waiting) {
                totalServerWaitNanos.addAndGet(System.nanoTime() - start);
            }
        }
    }

    public void awaitRenderFrames(long n) throws InterruptedException {
        if (n <= 0) return;
        long start = System.nanoTime();
        lock.lock();
        try {
            long target = completedRenderFrames + n;
            while (completedRenderFrames < target) {
                renderBarrierChanged.await();
            }
        } finally {
            lock.unlock();
            totalRenderWaitNanos.addAndGet(System.nanoTime() - start);
        }
    }

    public void awaitServerThenRender(long serverTicks, long renderFrames) throws InterruptedException {
        awaitServerTicks(serverTicks);
        awaitRenderFrames(renderFrames);
    }

    public void setWorldReady(boolean ready) {
        lock.lock();
        try {
            worldReady = ready;
            readyChanged.signalAll();
        } finally {
            lock.unlock();
        }
    }

    public boolean isWorldReady() {
        lock.lock();
        try {
            return worldReady;
        } finally {
            lock.unlock();
        }
    }

    public void awaitWorldReady() throws InterruptedException {
        lock.lock();
        try {
            while (!worldReady) {
                readyChanged.await();
            }
        } finally {
            lock.unlock();
        }
    }

    public boolean isPaused() {
        lock.lock();
        try {
            return paused;
        } finally {
            lock.unlock();
        }
    }

    public long getPendingTicks() {
        lock.lock();
        try {
            return pendingTicks;
        } finally {
            lock.unlock();
        }
    }

    public long getCompletedServerTicks() {
        lock.lock();
        try {
            return completedServerTicks;
        } finally {
            lock.unlock();
        }
    }

    public long getCompletedRenderFrames() {
        lock.lock();
        try {
            return completedRenderFrames;
        } finally {
            lock.unlock();
        }
    }

    public long getCompletedTicks() {
        return getCompletedServerTicks();
    }

    public void setClientPaused(boolean v) {
        clientPaused.set(v);
    }

    public boolean isClientPaused() {
        return clientPaused.get();
    }

    public void requestRenderOnce() {
        renderOnce.set(true);
    }

    public boolean consumeRenderOnce() {
        return renderOnce.compareAndSet(true, false);
    }

    public int getTickRate() {
        return tickRate;
    }

    public void setTickRate(int rate) {
        if (rate < 1) rate = 1;
        if (rate > 1000) rate = 1000;
        this.tickRate = rate;
    }

    public int getRenderCadence() {
        return renderCadence;
    }

    public void setRenderCadence(int cadence) {
        if (cadence < 1) cadence = 1;
        this.renderCadence = cadence;
    }

    public long getMaxStepBatch() {
        return maxStepBatch;
    }

    public void setMaxStepBatch(long batch) {
        if (batch < 1) batch = 1;
        this.maxStepBatch = batch;
    }

    public void recordCommand(String verb) {
        totalCommands.incrementAndGet();
        verbCounts.computeIfAbsent(verb, k -> new AtomicLong(0L)).incrementAndGet();
    }

    public void recordError() {
        totalErrors.incrementAndGet();
    }

    public void recordInterrupted() {
        totalInterrupted.incrementAndGet();
    }

    public void recordCommandLatencyNanos(long nanos) {
        if (nanos > 0) {
            totalCommandLatencyNanos.addAndGet(nanos);
        }
    }

    public long getTotalCommands() {
        return totalCommands.get();
    }

    public long getTotalErrors() {
        return totalErrors.get();
    }

    public long getTotalInterrupted() {
        return totalInterrupted.get();
    }

    public long getTotalCommandLatencyNanos() {
        return totalCommandLatencyNanos.get();
    }

    public long getTotalServerWaitNanos() {
        return totalServerWaitNanos.get();
    }

    public long getTotalRenderWaitNanos() {
        return totalRenderWaitNanos.get();
    }

    public Map<String, Long> getVerbCountsSnapshot() {
        Map<String, Long> out = new HashMap<>();
        for (Map.Entry<String, AtomicLong> e : verbCounts.entrySet()) {
            out.put(e.getKey(), e.getValue().get());
        }
        return out;
    }

    public void shutdown() {
        lock.lock();
        try {
            paused = false;
            pendingTicks = 0L;
            worldReady = false;
            budgetChanged.signalAll();
            serverBarrierChanged.signalAll();
            renderBarrierChanged.signalAll();
            readyChanged.signalAll();
        } finally {
            lock.unlock();
        }
    }

    public String statusLine() {
        lock.lock();
        try {
            return String.format(
                "paused=%s pendingTicks=%d completedServerTicks=%d completedRenderFrames=%d tickRate=%d clientPaused=%s renderCadence=%d maxStepBatch=%d worldReady=%s",
                paused, pendingTicks, completedServerTicks, completedRenderFrames, tickRate, clientPaused.get(), renderCadence, maxStepBatch, worldReady
            );
        } finally {
            lock.unlock();
        }
    }
}
