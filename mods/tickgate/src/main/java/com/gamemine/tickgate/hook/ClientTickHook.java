package com.gamemine.tickgate.hook;

import com.gamemine.tickgate.TickGate;
import com.gamemine.tickgate.core.TickGateFrameCapture;
import com.gamemine.tickgate.core.TickGateState;

import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.common.EventBusSubscriber;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.client.event.RenderFrameEvent;

/**
 * Optional client-side gating.
 *
 * The server tick gate is enough for headless / dedicated-server training.
 * On a client-host (integrated server) you may additionally want to freeze
 * the client tick loop so input / animations / UI stop advancing.
 *
 * Caveat: the client tick loop runs on the render thread, so sleeping here
 * will make the window feel frozen (still draggable / closeable by the OS,
 * but no frames advance). Only enable client_pause when you actually want
 * that behavior (e.g. headless RL where nothing reads the framebuffer).
 *
 * Render policy: we do NOT block the render thread on render_once — we
 * simply expose a flag that flips on each completed frame, so an external
 * screen-grab capture can poll "was a new frame drawn since I last asked?".
 */
@EventBusSubscriber(modid = TickGate.MODID, value = Dist.CLIENT)
public final class ClientTickHook {

    private ClientTickHook() {}

    @SubscribeEvent
    public static void onClientTickPre(ClientTickEvent.Pre event) {
        TickGateState state = TickGateState.get();
        if (!state.isClientPaused()) return;

        // Short-sleep busy-wait. We're on the render thread, so the window
        // will not redraw while we're here — opt in only when that's wanted.
        while (state.isClientPaused()) {
            try {
                Thread.sleep(1L);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    @SubscribeEvent
    public static void onRenderFramePost(RenderFrameEvent.Post event) {
        TickGateState state = TickGateState.get();
        state.recordRenderFrameCompleted();
        TickGateFrameCapture.get().captureIfRequested(state.getCompletedRenderFrames());
        state.consumeRenderOnce();
    }
}
