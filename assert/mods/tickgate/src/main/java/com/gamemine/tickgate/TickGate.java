package com.gamemine.tickgate;

import org.slf4j.Logger;

import com.gamemine.tickgate.command.TickGateCommand;
import com.gamemine.tickgate.core.TickGateState;
import com.gamemine.tickgate.hook.ServerTickHook;
import com.gamemine.tickgate.ipc.TickGateIpcServer;
import com.mojang.logging.LogUtils;

import net.minecraft.server.MinecraftServer;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.ModContainer;
import net.neoforged.fml.common.Mod;
import net.neoforged.fml.config.ModConfig;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.RegisterCommandsEvent;
import net.neoforged.neoforge.event.server.ServerStartedEvent;
import net.neoforged.neoforge.event.server.ServerStartingEvent;
import net.neoforged.neoforge.event.server.ServerStoppingEvent;

@Mod(TickGate.MODID)
public final class TickGate {

    public static final String MODID = "tickgate";
    public static final Logger LOGGER = LogUtils.getLogger();

    private static volatile MinecraftServer currentServer;

    public TickGate(IEventBus modEventBus, ModContainer modContainer) {
        modContainer.registerConfig(ModConfig.Type.COMMON, Config.SPEC);

        NeoForge.EVENT_BUS.register(this);
        NeoForge.EVENT_BUS.register(ServerTickHook.class);
    }

    public static MinecraftServer getCurrentServer() {
        return currentServer;
    }

    @SubscribeEvent
    public void onRegisterCommands(RegisterCommandsEvent event) {
        TickGateCommand.register(event.getDispatcher());
    }

    @SubscribeEvent
    public void onServerStarting(ServerStartingEvent event) {
        currentServer = event.getServer();

        TickGateIpcServer.startIfEnabled(
            Config.IPC_ENABLED.get(),
            Config.IPC_HOST.get(),
            Config.IPC_PORT.get()
        );

        TickGateState state = TickGateState.get();
        state.setWorldReady(false);

        int rate = Config.DEFAULT_TICK_RATE.get();
        state.setTickRate(rate);
        event.getServer().tickRateManager().setTickRate((float) rate);

        state.setRenderCadence(Config.RENDER_CADENCE.get());
        state.setMaxStepBatch(Config.MAX_STEP_BATCH.get());

        if (Config.PAUSE_ON_STARTUP.get()) {
            state.pause();
            LOGGER.info("TickGate: world starts paused (pauseOnStartup=true)");
        }
    }

    @SubscribeEvent
    public void onServerStarted(ServerStartedEvent event) {
        TickGateState.get().setWorldReady(true);
        LOGGER.info("TickGate ready — {}", TickGateState.get().statusLine());
    }

    @SubscribeEvent
    public void onServerStopping(ServerStoppingEvent event) {
        TickGateState.get().shutdown();
        TickGateIpcServer.stop();
        currentServer = null;
    }
}
