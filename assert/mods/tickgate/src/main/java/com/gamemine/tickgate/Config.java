package com.gamemine.tickgate;

import net.neoforged.neoforge.common.ModConfigSpec;

/**
 * TickGate common config.
 *
 *   ipcEnabled       — start the TCP IPC server on server-startup
 *   ipcHost          — bind address (default 127.0.0.1; do NOT use 0.0.0.0 on a public box)
 *   ipcPort          — bind port (default 25575, chosen to mirror RCON's default port number
 *                      but it has nothing to do with RCON; change if it conflicts)
 *   pauseOnStartup   — start the world in a paused state (good for RL — controller attaches first)
 *   defaultTickRate  — server tick rate to apply on startup (vanilla = 20)
 *   renderCadence    — for step_observe default path: wait one render frame every N steps
 *   maxStepBatch     — max n accepted by step-like verbs
 *   autoEnterWorldEnabled — client startup auto-enter world toggle
 *   autoEnterMode    — loadExisting or createFromSeed
 *   autoWorldName    — target world name for auto-enter
 *   autoWorldSeed    — seed used in createFromSeed mode
 *   autoWorldCreative — create world in creative mode in createFromSeed mode
 */
public final class Config {

    private static final ModConfigSpec.Builder B = new ModConfigSpec.Builder();

    public static final ModConfigSpec.BooleanValue IPC_ENABLED = B
        .comment("Whether to start the TickGate TCP IPC server on server startup.")
        .define("ipcEnabled", true);

    public static final ModConfigSpec.ConfigValue<String> IPC_HOST = B
        .comment("Host/interface to bind the IPC server to. Keep 127.0.0.1 unless you know what you're doing.")
        .define("ipcHost", "127.0.0.1");

    public static final ModConfigSpec.IntValue IPC_PORT = B
        .comment("TCP port for the IPC server.")
        .defineInRange("ipcPort", 25575, 1, 65535);

    public static final ModConfigSpec.BooleanValue PAUSE_ON_STARTUP = B
        .comment("If true, the world starts paused (waiting for an external `resume` or `step`).")
        .define("pauseOnStartup", false);

    public static final ModConfigSpec.IntValue DEFAULT_TICK_RATE = B
        .comment("Server tick rate applied at startup (Hz). Vanilla = 20.")
        .defineInRange("defaultTickRate", 20, 1, 1000);

    public static final ModConfigSpec.IntValue RENDER_CADENCE = B
        .comment("Render cadence for step_observe default path. 1 means every step waits for a render frame.")
        .defineInRange("renderCadence", 1, 1, 1_000_000);

    public static final ModConfigSpec.LongValue MAX_STEP_BATCH = B
        .comment("Maximum n accepted by step-like IPC/command verbs.")
        .defineInRange("maxStepBatch", 1_000_000L, 1L, Long.MAX_VALUE);

    public static final ModConfigSpec.BooleanValue AUTO_ENTER_WORLD_ENABLED = B
        .comment("If true, client tries to auto-enter a world on startup.")
        .define("autoEnterWorldEnabled", false);

    public static final ModConfigSpec.ConfigValue<String> AUTO_ENTER_MODE = B
        .comment("Auto-enter mode: loadExisting or createFromSeed")
        .define("autoEnterMode", "loadExisting");

    public static final ModConfigSpec.ConfigValue<String> AUTO_WORLD_NAME = B
        .comment("Target world name for auto-enter.")
        .define("autoWorldName", "New World");

    public static final ModConfigSpec.ConfigValue<String> AUTO_WORLD_SEED = B
        .comment("Seed for createFromSeed mode (string accepted).")
        .define("autoWorldSeed", "12345");

    public static final ModConfigSpec.BooleanValue AUTO_WORLD_CREATIVE = B
        .comment("If true, createFromSeed mode uses creative mode.")
        .define("autoWorldCreative", false);

    public static final ModConfigSpec SPEC = B.build();

    private Config() {}
}
