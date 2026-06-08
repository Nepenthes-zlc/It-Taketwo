package com.gamemine.tickgate.hook;

import com.gamemine.tickgate.TickGate;
import com.gamemine.tickgate.core.TickGateState;

import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.neoforge.event.tick.ServerTickEvent;

/**
 * Hooks into the server tick loop and blocks it on the TickGate.
 *
 * Pre  — wait until pause is cleared or budget is granted, then consume one budget.
 * Post — record that a tick completed, wake any waiters (used by IPC step+wait).
 *
 * Runs on the server thread; awaiting here parks the whole server, which is
 * exactly what an external "step" controller wants.
 */
public final class ServerTickHook {

    private ServerTickHook() {}

    @SubscribeEvent
    public static void onServerTickPre(ServerTickEvent.Pre event) {
        try {
            TickGateState.get().awaitTickPermission();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            TickGate.LOGGER.warn("Server tick wait interrupted; allowing tick to proceed");
        }
    }

    @SubscribeEvent
    public static void onServerTickPost(ServerTickEvent.Post event) {
        TickGateState.get().recordServerTickCompleted();
    }
}
