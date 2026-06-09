package com.gamemine.tickgate.command;

import com.gamemine.tickgate.TickGate;
import com.gamemine.tickgate.core.TickGateState;
import com.mojang.brigadier.CommandDispatcher;
import com.mojang.brigadier.arguments.IntegerArgumentType;
import com.mojang.brigadier.arguments.LongArgumentType;
import com.mojang.brigadier.builder.LiteralArgumentBuilder;

import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;

/**
 * In-game command tree:
 *
 *   /tickgate pause
 *   /tickgate resume
 *   /tickgate step <n>
 *   /tickgate status
 *   /tickgate rate <n>
 *   /tickgate render_once
 *
 * Op-level 2 required (same level as /gamemode etc.) so a regular player
 * can't accidentally freeze the server.
 *
 * NOTE: Minecraft 1.20.3+ ships a vanilla /tick command (freeze/step/rate)
 * that overlaps with most of this. We keep our own because:
 *   - it shares state with the IPC server (vanilla /tick does not),
 *   - external Python controllers should talk to ONE source of truth,
 *   - we expose render_once and a single-line machine-readable status.
 */
public final class TickGateCommand {

    private TickGateCommand() {}

    public static void register(CommandDispatcher<CommandSourceStack> dispatcher) {
        LiteralArgumentBuilder<CommandSourceStack> root = Commands.literal("tickgate")
            .requires(src -> src.hasPermission(2));

        root.then(Commands.literal("pause").executes(ctx -> {
            TickGateState.get().pause();
            ctx.getSource().sendSuccess(() -> Component.literal("TickGate: paused"), true);
            return 1;
        }));

        root.then(Commands.literal("resume").executes(ctx -> {
            TickGateState.get().resume();
            ctx.getSource().sendSuccess(() -> Component.literal("TickGate: resumed"), true);
            return 1;
        }));

        root.then(Commands.literal("step")
            .then(Commands.argument("n", IntegerArgumentType.integer(1, 1_000_000))
                .executes(ctx -> {
                    int n = IntegerArgumentType.getInteger(ctx, "n");
                    TickGateState state = TickGateState.get();
                    state.validateStepBatch(n);
                    state.addPendingTicks(n);
                    ctx.getSource().sendSuccess(
                        () -> Component.literal("TickGate: stepping " + n + " tick(s)"), true);
                    return n;
                })));

        root.then(Commands.literal("status").executes(ctx -> {
            TickGateState state = TickGateState.get();
            String basic = String.format(
                "paused=%s pendingTicks=%d tickRate=%d clientPaused=%s renderCadence=%d maxStepBatch=%d",
                state.isPaused(), state.getPendingTicks(), state.getTickRate(), state.isClientPaused(),
                state.getRenderCadence(), state.getMaxStepBatch()
            );
            String barriers = String.format(
                "completedServerTicks=%d completedRenderFrames=%d",
                state.getCompletedServerTicks(), state.getCompletedRenderFrames()
            );
            ctx.getSource().sendSuccess(() -> Component.literal("TickGate: " + basic), false);
            ctx.getSource().sendSuccess(() -> Component.literal("TickGate: " + barriers), false);
            return 1;
        }));

        root.then(Commands.literal("step_wait_server")
            .then(Commands.argument("n", IntegerArgumentType.integer(1, 1_000_000))
                .executes(ctx -> {
                    int n = IntegerArgumentType.getInteger(ctx, "n");
                    TickGateState state = TickGateState.get();
                    state.validateStepBatch(n);
                    state.addPendingTicks(n);
                    try {
                        state.awaitServerTicks(n);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        ctx.getSource().sendFailure(Component.literal("TickGate: interrupted while waiting server barrier"));
                        return 0;
                    }
                    ctx.getSource().sendSuccess(
                        () -> Component.literal("TickGate: server barrier completed for " + n + " tick(s)"),
                        false
                    );
                    return n;
                })));

        root.then(Commands.literal("step_wait_client")
            .then(Commands.argument("n", IntegerArgumentType.integer(1, 1_000_000))
                .executes(ctx -> {
                    int n = IntegerArgumentType.getInteger(ctx, "n");
                    try {
                        TickGateState.get().awaitRenderFrames(n);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        ctx.getSource().sendFailure(Component.literal("TickGate: interrupted while waiting render barrier"));
                        return 0;
                    }
                    ctx.getSource().sendSuccess(
                        () -> Component.literal("TickGate: render barrier completed for " + n + " frame(s)"),
                        false
                    );
                    return n;
                })));

        root.then(Commands.literal("step_wait_dual")
            .then(Commands.argument("n", IntegerArgumentType.integer(1, 1_000_000))
                .executes(ctx -> {
                    int n = IntegerArgumentType.getInteger(ctx, "n");
                    TickGateState state = TickGateState.get();
                    state.validateStepBatch(n);
                    state.addPendingTicks(n);
                    try {
                        state.awaitServerThenRender(n, 1);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        ctx.getSource().sendFailure(Component.literal("TickGate: interrupted while waiting dual barrier"));
                        return 0;
                    }
                    ctx.getSource().sendSuccess(
                        () -> Component.literal("TickGate: dual barrier completed (server " + n + " + render 1)"),
                        false
                    );
                    return n;
                })));

        root.then(Commands.literal("rate")
            .then(Commands.argument("hz", IntegerArgumentType.integer(1, 1000))
                .executes(ctx -> {
                    int hz = IntegerArgumentType.getInteger(ctx, "hz");
                    applyTickRate(hz);
                    ctx.getSource().sendSuccess(
                        () -> Component.literal("TickGate: tick rate set to " + hz + " Hz"), true);
                    return hz;
                })));

        root.then(Commands.literal("set_render_cadence")
            .then(Commands.argument("n", IntegerArgumentType.integer(1, 1_000_000))
                .executes(ctx -> {
                    int cadence = IntegerArgumentType.getInteger(ctx, "n");
                    TickGateState.get().setRenderCadence(cadence);
                    ctx.getSource().sendSuccess(
                        () -> Component.literal("TickGate: render cadence set to " + cadence), true);
                    return cadence;
                })));

        root.then(Commands.literal("set_max_step_batch")
            .then(Commands.argument("n", LongArgumentType.longArg(1, Long.MAX_VALUE))
                .executes(ctx -> {
                    long batch = LongArgumentType.getLong(ctx, "n");
                    TickGateState.get().setMaxStepBatch(batch);
                    ctx.getSource().sendSuccess(
                        () -> Component.literal("TickGate: max step batch set to " + batch), true);
                    return 1;
                })));

        root.then(Commands.literal("render_once").executes(ctx -> {
            TickGateState.get().requestRenderOnce();
            ctx.getSource().sendSuccess(
                () -> Component.literal("TickGate: render_once requested"), false);
            return 1;
        }));

        dispatcher.register(root);
    }

    private static void applyTickRate(int hz) {
        TickGateState state = TickGateState.get();
        state.setTickRate(hz);
        MinecraftServer server = TickGate.getCurrentServer();
        if (server != null) {
            server.execute(() -> server.tickRateManager().setTickRate((float) hz));
        }
    }
}
