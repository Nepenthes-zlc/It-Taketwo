package com.gamemine.tickgate.hook;

import com.gamemine.tickgate.Config;
import com.gamemine.tickgate.TickGate;
import com.gamemine.tickgate.core.TickGateState;

import net.minecraft.client.Minecraft;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.common.EventBusSubscriber;
import net.neoforged.neoforge.client.event.ClientTickEvent;

import java.lang.reflect.Method;
import java.util.Locale;

@EventBusSubscriber(modid = TickGate.MODID, value = Dist.CLIENT)
public final class ClientAutoWorldHook {

    private static boolean attemptedAutoEnter = false;
    private static long ticksSinceStart = 0L;

    private ClientAutoWorldHook() {}

    @SubscribeEvent
    public static void onClientTickPost(ClientTickEvent.Post event) {
        Minecraft mc = Minecraft.getInstance();
        TickGateState state = TickGateState.get();

        if (mc.level != null) {
            state.setWorldReady(true);
            return;
        }

        state.setWorldReady(false);

        if (!Config.AUTO_ENTER_WORLD_ENABLED.get()) return;
        if (attemptedAutoEnter) return;

        ticksSinceStart++;
        if (ticksSinceStart < 20) return;
        if (mc.screen == null) return;

        String screenName = mc.screen.getClass().getSimpleName().toLowerCase(Locale.ROOT);
        if (!screenName.contains("title") && !screenName.contains("menu")) return;

        attemptedAutoEnter = true;
        String mode = Config.AUTO_ENTER_MODE.get().trim().toLowerCase(Locale.ROOT);
        String worldName = Config.AUTO_WORLD_NAME.get().trim();
        String seed = Config.AUTO_WORLD_SEED.get().trim();

        boolean ok;
        if ("createfromseed".equals(mode)) {
            ok = tryCreateFromSeed(mc, worldName, seed, Config.AUTO_WORLD_CREATIVE.get());
            if (!ok) {
                TickGate.LOGGER.warn("TickGate auto-enter createFromSeed failed, trying loadExisting fallback");
                ok = tryLoadExisting(mc, worldName);
            }
        } else {
            ok = tryLoadExisting(mc, worldName);
        }

        if (!ok) {
            TickGate.LOGGER.error("TickGate auto-enter failed for mode={}, world={}", mode, worldName);
        }
    }

    private static boolean tryLoadExisting(Minecraft mc, String worldName) {
        if (worldName.isEmpty()) return false;

        try {
            Object flows = mc.getClass().getMethod("createWorldOpenFlows").invoke(mc);
            Method[] methods = flows.getClass().getMethods();
            for (Method m : methods) {
                String name = m.getName().toLowerCase(Locale.ROOT);
                Class<?>[] p = m.getParameterTypes();
                if (!(name.contains("load") || name.contains("open"))) continue;
                if (p.length == 1 && p[0] == String.class) {
                    m.invoke(flows, worldName);
                    TickGate.LOGGER.info("TickGate auto-enter loadExisting invoked via {}", m.getName());
                    return true;
                }
                if (p.length == 2 && p[0] == String.class && Runnable.class.isAssignableFrom(p[1])) {
                    m.invoke(flows, worldName, (Runnable) () -> {});
                    TickGate.LOGGER.info("TickGate auto-enter loadExisting invoked via {}", m.getName());
                    return true;
                }
                if (p.length == 2 && p[0] == String.class && p[1] == boolean.class) {
                    m.invoke(flows, worldName, false);
                    TickGate.LOGGER.info("TickGate auto-enter loadExisting invoked via {}", m.getName());
                    return true;
                }
            }
        } catch (Exception e) {
            TickGate.LOGGER.warn("TickGate auto-enter loadExisting reflection failed: {}", e.toString());
        }

        return false;
    }

    private static boolean tryCreateFromSeed(Minecraft mc, String worldName, String seed, boolean creative) {
        try {
            Object flows = mc.getClass().getMethod("createWorldOpenFlows").invoke(mc);
            Method[] methods = flows.getClass().getMethods();
            for (Method m : methods) {
                String name = m.getName().toLowerCase(Locale.ROOT);
                if (!(name.contains("create") || name.contains("fresh"))) continue;
                Class<?>[] p = m.getParameterTypes();

                if (p.length == 0) {
                    continue;
                }

                if (p.length == 1 && p[0] == String.class) {
                    m.invoke(flows, worldName);
                    TickGate.LOGGER.info("TickGate auto-enter createFromSeed invoked via {}", m.getName());
                    return true;
                }

                if (p.length == 2 && p[0] == String.class && p[1] == String.class) {
                    m.invoke(flows, worldName, seed);
                    TickGate.LOGGER.info("TickGate auto-enter createFromSeed invoked via {}", m.getName());
                    return true;
                }

                if (p.length == 3 && p[0] == String.class && p[1] == String.class && p[2] == boolean.class) {
                    m.invoke(flows, worldName, seed, creative);
                    TickGate.LOGGER.info("TickGate auto-enter createFromSeed invoked via {}", m.getName());
                    return true;
                }
            }
        } catch (Exception e) {
            TickGate.LOGGER.warn("TickGate auto-enter createFromSeed reflection failed: {}", e.toString());
        }

        return false;
    }
}
