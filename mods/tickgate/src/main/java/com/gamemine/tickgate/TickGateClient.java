package com.gamemine.tickgate;

import net.neoforged.api.distmarker.Dist;
import net.neoforged.fml.ModContainer;
import net.neoforged.fml.common.Mod;
import net.neoforged.neoforge.client.gui.ConfigurationScreen;
import net.neoforged.neoforge.client.gui.IConfigScreenFactory;

/**
 * Client-only entry point: only purpose is to register the in-game config screen.
 * Tick/render hooks live in {@link com.gamemine.tickgate.hook.ClientTickHook}
 * which is auto-discovered via @EventBusSubscriber.
 */
@Mod(value = TickGate.MODID, dist = Dist.CLIENT)
public final class TickGateClient {

    public TickGateClient(ModContainer container) {
        container.registerExtensionPoint(IConfigScreenFactory.class, ConfigurationScreen::new);
    }
}
