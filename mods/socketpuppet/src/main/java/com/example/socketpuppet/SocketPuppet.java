package com.example.socketpuppet;

import com.mojang.logging.LogUtils;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.world.InteractionHand;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

import java.util.List;
import java.util.Locale;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.bus.api.SubscribeEvent;
import net.neoforged.fml.common.Mod;
import net.neoforged.fml.event.lifecycle.FMLCommonSetupEvent;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.client.event.MovementInputUpdateEvent;
import net.neoforged.neoforge.client.event.RenderPlayerEvent;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.tick.PlayerTickEvent;
import org.slf4j.Logger;

@Mod(SocketPuppet.MODID)
public class SocketPuppet {
    // 这里的 MODID 必须与你 mods.toml 中的 modId 一致
    public static final String MODID = "socketpuppet";
    public static final Logger LOGGER = LogUtils.getLogger();

    private PuppetServer puppetServer;

    // --- 状态变量 (由 Server 线程修改，主线程读取) ---
    public static int listeningPort = 0;
    /** 当前操作的代理/假人名称："default" 表示本地玩家；其它名字为命名假人（当前通过 /execute 控制，接入假人模组后可解析为实体，与玩家共用同一套 apply 逻辑） */
    public static volatile String currentAgentName = "default";
    public static volatile String currentAction = "Waiting...";

    // 移动控制
    public static volatile float targetForward = 0.0f;
    public static volatile float targetStrafe = 0.0f;
    public static volatile boolean isJumping = false;
    public static volatile boolean isSneaking = false;
    public static volatile boolean isSprinting = false;
    
    // 移动倒计时 (Tick)
    public static volatile int movementTicksLeft = 0;

    // 视角控制
    // 移除 overrideLook，改为一次性触发
    public static volatile boolean shouldLookAbsolute = false;
    public static volatile float targetYaw = 0.0f;
    public static volatile float targetPitch = 0.0f;
    /** look 插值时长（秒），>0 时使用平滑插值而非瞬间设置 */
    public static volatile float targetLookDuration = 0.0f;
    
    // 相对视角控制
    public static volatile boolean shouldTurnRelative = false;
    public static volatile float targetYawRelative = 0.0f;
    public static volatile float targetPitchRelative = 0.0f;
    // 插值相关
    public static volatile float targetTurnDuration = 0.0f; // in seconds
    private float interpolatedTurnYaw = 0.0f;
    private float interpolatedTurnPitch = 0.0f;
    private float remainingTurnTime = 0.0f;

    // 动作标志
    public static volatile boolean shouldLeftClick = false;
    public static volatile boolean shouldRightClick = false;
    public static volatile boolean shouldOpenInventory = false;
    public static volatile boolean shouldGrab = false; // 抓取方块
    public static volatile boolean shouldQuerySight = false; // 查询视线方块
    /** 非空时在本 tick 查询该名字对应实体的位置与朝向（客户端已加载范围内） */
    public static class EntityPoseQuery {
        public final String name;
        public final java.io.PrintWriter writer;

        public EntityPoseQuery(String name, java.io.PrintWriter writer) {
            this.name = name;
            this.writer = writer;
        }
    }
    public static volatile EntityPoseQuery pendingEntityPoseQuery = null;
    public static volatile boolean shouldGetReachable = false; // 查询周边3x3可达性
    
    // 功能键标志
    public static volatile boolean toggleF1 = false;
    public static volatile boolean toggleF2 = false; // 截图
    public static volatile String pendingCameraType = null;
    public static volatile String pendingCameraEntityName = null;
    /** 当前被相机附着的实体（命名假人）：渲染时取消其自身模型，避免第一人称里挡脸。null 表示相机在本地玩家或未附着。 */
    public static volatile Entity hiddenCameraEntity = null;

    // 待执行的聊天/指令队列
    public static final java.util.Queue<String> commandQueue = new java.util.concurrent.ConcurrentLinkedQueue<>();

    public static class AgentMotionIntent {
        public double forwardRemaining = 0.0;  // 正=前，负=后（米）
        public double strafeRemaining = 0.0;   // 正=左，负=右（米）
        public double deltaYaw = 0.0;
        public double deltaPitch = 0.0;
        public boolean wantsJump = false;
    }

    /** 命名假人：由服务端按「实体+速度/转角」分别驱动，避免多 agent 动作互相覆盖 */
    public static final ConcurrentMap<String, AgentMotionIntent> namedAgentIntents = new ConcurrentHashMap<>();
    private static final double NAMED_AGENT_STEP_PER_TICK = 4.3 / 20.0;

    public static AgentMotionIntent intentForNamedAgent(String name) {
        return namedAgentIntents.computeIfAbsent(name.toLowerCase(Locale.ROOT), ignored -> new AgentMotionIntent());
    }
    
    // 方块查询
    public static volatile net.minecraft.core.BlockPos pendingBlockQuery = null;
    public static volatile boolean shouldQueryHand = false; // 查询手持物品
    public static volatile boolean shouldClearInventory = false; // 清空物品栏
    public static volatile java.io.PrintWriter currentClientWriter = null;
    
    // 自动瞄准
    public static class AimRequest {
        public final String blockName;
        public final double radius;
        public final double maxAngle; // 最大允许转动角度 (度)
        public final float duration; // 瞄准耗时 (秒)

        public AimRequest(String blockName, double radius, double maxAngle, float duration) {
            this.blockName = blockName;
            this.radius = radius;
            this.maxAngle = maxAngle;
            this.duration = duration;
        }
    }
    public static volatile AimRequest pendingAimRequest = null;

    public static class AimPosRequest {
        public final double x, y, z;
        public final double maxDist;
        public final float duration;
        public final double maxAngle;

        public AimPosRequest(double x, double y, double z, double maxDist, float duration, double maxAngle) {
            this.x = x;
            this.y = y;
            this.z = z;
            this.maxDist = maxDist;
            this.duration = duration;
            this.maxAngle = maxAngle;
        }
    }
    public static volatile AimPosRequest pendingAimPosRequest = null;

    public SocketPuppet(IEventBus modEventBus) {
        // 注册生命周期事件
        modEventBus.addListener(this::setup);
        // 注册游戏内事件 (Tick, Input 等)
        NeoForge.EVENT_BUS.register(this);
    }

    private void setup(final FMLCommonSetupEvent event) {
        LOGGER.debug("SocketPuppet 初始化中...");
        new Thread(() -> {
            // 尝试绑定端口范围：12345 ~ 12445
            for (int port = 12345; port <= 12445; port++) {
                try {
                    puppetServer = new PuppetServer(port);
                    puppetServer.start(); // 阻塞运行

                    listeningPort = port;
                    LOGGER.debug("PuppetServer 成功启动于端口: " + port);
                    break;
                } catch (Exception e) {
                    LOGGER.warn("端口 " + port + " 被占用，尝试下一个...");
                }
            }
            if (listeningPort == 0) {
                LOGGER.error("无法找到可用端口！");
            }
        }, "SocketPuppet-Server-Thread").start();
    }

    // 1.21 输入拦截
    @SubscribeEvent
    public void onInputUpdate(MovementInputUpdateEvent event) {
        var input = event.getInput();

        if (targetForward != 0.0f) {
            input.forwardImpulse = targetForward;
            input.up = targetForward > 0;
            input.down = targetForward < 0;
        }
        if (targetStrafe != 0.0f) {
            input.leftImpulse = targetStrafe;
            input.left = targetStrafe > 0;
            input.right = targetStrafe < 0;
        }
        if (isJumping) input.jumping = true;
        if (isSneaking) {
            input.shiftKeyDown = true;
            input.leftImpulse *= 0.3D;
            input.forwardImpulse *= 0.3D;
        }
    }

    // 客户端 Tick (用于 HUD 更新、视角强制和输入模拟)
    @SubscribeEvent
    public void onClientTick(ClientTickEvent.Post event) {
        Minecraft mc = Minecraft.getInstance();
        if (mc.player == null) return;

        // 处理移动倒计时 (确保每次只在逻辑帧更新，ClientTick 可能会比逻辑帧快，但通常可以用)
        // 严格来说应该在 PlayerTick 或 ServerTick，但这是客户端模组。
        // 为了简单起见，我们在 ClientTick 更新，如果需要更精确，可以用 ClientTickEvent.Pre 配合计数
        if (movementTicksLeft > 0) {
            movementTicksLeft--;
            if (movementTicksLeft <= 0) {
                // 倒计时结束，停止移动
                targetForward = 0.0f;
                targetStrafe = 0.0f;
                isJumping = false; // 跳跃通常是一次性的，但也可能持续
                currentAction = "Waiting...";
            }
        }

        // 1. 视角控制 (一次性或带 duration 的插值)
        if (shouldLookAbsolute) {
            if (targetLookDuration > 0) {
                // 插值到目标绝对角度，复用 turn 的插值逻辑
                float dy = net.minecraft.util.Mth.wrapDegrees(targetYaw - mc.player.getYRot());
                float dp = targetPitch - mc.player.getXRot();
                interpolatedTurnYaw = dy;
                interpolatedTurnPitch = dp;
                remainingTurnTime = targetLookDuration;
                targetLookDuration = 0;
            } else {
                mc.player.setYRot(targetYaw);
                mc.player.setXRot(targetPitch);
                mc.player.yHeadRot = targetYaw;
                mc.player.yRotO = targetYaw;
                mc.player.xRotO = targetPitch;
                remainingTurnTime = 0; // 取消正在进行的平滑转动
            }
            shouldLookAbsolute = false;
        } 
        
        if (shouldTurnRelative) {
            // 收到新的转动指令
            if (targetTurnDuration > 0) {
                // 开启插值模式
                interpolatedTurnYaw = targetYawRelative;
                interpolatedTurnPitch = targetPitchRelative;
                remainingTurnTime = targetTurnDuration;
            } else {
                // 立即转动 (之前的逻辑)
                float newYaw = mc.player.getYRot() + targetYawRelative;
                float newPitch = mc.player.getXRot() + targetPitchRelative;
                newPitch = net.minecraft.util.Mth.clamp(newPitch, -90.0F, 90.0F);

                mc.player.setYRot(newYaw);
                mc.player.setXRot(newPitch);
                mc.player.yHeadRot = newYaw; 
                
                mc.player.yRotO = newYaw - targetYawRelative; 
                mc.player.xRotO = newPitch - targetPitchRelative;
            }
            shouldTurnRelative = false; 
        }

        // 处理平滑插值转动
        if (remainingTurnTime > 0) {
            float dt = mc.getTimer().getGameTimeDeltaPartialTick(true); // 获取帧间隔 (Approx 0.05s per tick)
            // 由于 ClientTickEvent 是按 tick 触发的，我们可以假设每次调用间隔约 0.05s
            // 但为了更平滑，这里简单每 tick 处理一部分
            float stepTime = 0.05f; // 1 tick = 50ms
            
            if (remainingTurnTime <= stepTime) {
                stepTime = remainingTurnTime; // 最后一步
            }

            float progress = stepTime / remainingTurnTime; // 当前这一步占剩余总量的比例？不对。
            // 应该是：总增量 / (总时间 / 步长) = 每步增量
            // 但这里变量是动态的。 simpler approach:
            
            // 计算本 tick 需要转动的角度 = 总剩余角度 * (本 tick 时间 / 剩余时间)
            // 这样能保证在时间内转完
            float yawStep = interpolatedTurnYaw * (stepTime / remainingTurnTime);
            float pitchStep = interpolatedTurnPitch * (stepTime / remainingTurnTime);

            float newYaw = mc.player.getYRot() + yawStep;
            float newPitch = mc.player.getXRot() + pitchStep;
            newPitch = net.minecraft.util.Mth.clamp(newPitch, -90.0F, 90.0F);

            mc.player.setYRot(newYaw);
            mc.player.setXRot(newPitch);
            mc.player.yHeadRot = newYaw;
            
            // 插值模式下，yRotO 应该自然跟随，不需要手动干预过多，或者设为上一帧的值
            // 但为了保险，让 yRotO = 旧值
            // 这里不设置 yRotO，让 Minecraft 自动处理（它会自动记录上一帧的值）
            
            interpolatedTurnYaw -= yawStep;
            interpolatedTurnPitch -= pitchStep;
            remainingTurnTime -= stepTime;
        }

        // 2. 模拟点击和按键
        if (shouldLeftClick) {
            // 模拟左键攻击/挖掘 (使用反射调用 private 方法)
            invokePrivateMethod(mc, "startAttack");
            shouldLeftClick = false; // 触发一次后重置
        }
        if (shouldRightClick) {
            shouldRightClick = false;
            // 有界面打开时原版通常不处理“使用物品”
            if (mc.screen != null) {
                LOGGER.debug("use 被忽略：当前有界面打开 (screen != null)");
            } else {
                // 模拟右键交互/使用物品：优先 startUseItem(Hand)，再试无参
                boolean ok = invokeStartUseItem(mc);
                if (!ok) ok = invokePrivateMethodReturn(mc, "startUseItem");
                if (!ok) LOGGER.warn("use 未生效：startUseItem 调用失败，请查看上方异常。有界面时也会被原版忽略。");
            }
        }
        if (shouldOpenInventory) {
             // 模拟打开物品栏 (通常绑定到 'E')
             // 直接通过 Screen 打开可能会绕过某些逻辑，但通常足够
             if (mc.screen == null) {
                 mc.setScreen(new net.minecraft.client.gui.screens.inventory.InventoryScreen(mc.player));
             } else {
                 mc.player.closeContainer();
             }
             shouldOpenInventory = false;
        }

        if (shouldGrab) {
            shouldGrab = false;
            
            double grabRange = 10.0; // 实际抓取允许的最大距离
            double checkRange = 100.0; // 检测距离，用于判断是否"超出范围"
            
            // 使用长距离射线检测
            net.minecraft.world.phys.HitResult targetHit = mc.player.pick(checkRange, 0.0F, false);

            if (targetHit != null && targetHit.getType() == net.minecraft.world.phys.HitResult.Type.BLOCK) {
                net.minecraft.world.phys.BlockHitResult blockHit = (net.minecraft.world.phys.BlockHitResult) targetHit;
                net.minecraft.core.BlockPos pos = blockHit.getBlockPos();
                
                // 计算距离
                double distSq = pos.getCenter().distanceToSqr(mc.player.getEyePosition());
                
                if (distSq > grabRange * grabRange) {
                    if (currentClientWriter != null) {
                        currentClientWriter.println("FAIL: Out of Range (Distance " + String.format("%.1f", Math.sqrt(distSq)) + " > " + grabRange + ")");
                    }
                } else {
                    // 在范围内，执行抓取
                    net.minecraft.world.level.block.state.BlockState state = mc.level.getBlockState(pos);
                    
                    // 尝试获取方块对应的物品堆
                    net.minecraft.world.item.ItemStack itemStack = state.getCloneItemStack(blockHit, mc.level, pos, mc.player);
                    
                    if (!itemStack.isEmpty()) {
                        // 1. 放入主手
                        if (mc.player.isCreative()) {
                            // 36-44 是热栏
                            int slot = 36 + mc.player.getInventory().selected;
                            mc.gameMode.handleCreativeModeItemAdd(itemStack, slot);
                        } else {
                            // 生存模式仅设置本地，可能需要服务器权限或同步
                            mc.player.setItemInHand(net.minecraft.world.InteractionHand.MAIN_HAND, itemStack);
                        }
                        
                        // 2. 移除方块：用 replace 模式，不播放打碎音效、不产生破碎粒子，直接消失
                        if (mc.getConnection() != null) {
                            String cmd = String.format("setblock %d %d %d air replace", pos.getX(), pos.getY(), pos.getZ());
                            mc.getConnection().sendCommand(cmd);
                        }
                        
                        if (currentClientWriter != null) {
                            String itemName = itemStack.getHoverName().getString();
                            currentClientWriter.println("SUCCESS: Grabbed " + itemName + " at (" + pos.getX() + ", " + pos.getY() + ", " + pos.getZ() + ")");
                        }
                    } else {
                         if (currentClientWriter != null) {
                            currentClientWriter.println("FAIL: Empty Item");
                        }
                    }
                }
            } else {
                if (currentClientWriter != null) {
                    // 输出更详细的错误信息以便调试
                    String reason = (targetHit == null) ? "Null HitResult" : targetHit.getType().toString();
                    currentClientWriter.println("FAIL: No Block Targeted (" + reason + ")");
                }
            }
        }

        // 功能键模拟
        if (toggleF1) {
            mc.options.hideGui = !mc.options.hideGui;
            toggleF1 = false;
        }
        if (toggleF2) {
            net.minecraft.client.Screenshot.grab(
                mc.gameDirectory,
                mc.getMainRenderTarget(),
                (component) -> mc.gui.getChat().addMessage(component)
            );
            toggleF2 = false;
        }
        if (pendingCameraType != null) {
            String cameraType = pendingCameraType;
            pendingCameraType = null;
            if ("third_person_back".equals(cameraType)) {
                mc.options.setCameraType(net.minecraft.client.CameraType.THIRD_PERSON_BACK);
            } else if ("third_person_front".equals(cameraType)) {
                mc.options.setCameraType(net.minecraft.client.CameraType.THIRD_PERSON_FRONT);
            } else {
                mc.options.setCameraType(net.minecraft.client.CameraType.FIRST_PERSON);
            }
        }
        if (pendingCameraEntityName != null) {
            String cameraEntityName = pendingCameraEntityName;
            pendingCameraEntityName = null;
            if ("default".equalsIgnoreCase(cameraEntityName) || "player".equalsIgnoreCase(cameraEntityName) || "self".equalsIgnoreCase(cameraEntityName)) {
                mc.setCameraEntity(mc.player);
                hiddenCameraEntity = null;
                mc.options.setCameraType(net.minecraft.client.CameraType.FIRST_PERSON);
                currentAction = "POV: self";
            } else if (mc.level != null) {
                Vec3 c = mc.player.position();
                AABB box = new AABB(c, c).inflate(160.0);
                List<Entity> matches = mc.level.getEntitiesOfClass(Entity.class, box,
                        e -> entityPoseNameMatches(e, cameraEntityName));
                Entity best = null;
                double bestD = Double.MAX_VALUE;
                for (Entity e : matches) {
                    double d = e.distanceToSqr(mc.player);
                    if (d < bestD) {
                        bestD = d;
                        best = e;
                    }
                }
                if (best != null) {
                    mc.setCameraEntity(best);
                    hiddenCameraEntity = best;
                    mc.options.setCameraType(net.minecraft.client.CameraType.FIRST_PERSON);
                    currentAction = "POV: " + cameraEntityName;
                } else {
                    currentAction = "POV failed: " + cameraEntityName;
                }
            }
        }

        // 2.5 命名假人移动：不再在客户端用 /tp，改由服务端 PlayerTickEvent 按「实体+速度」驱动，与本体同逻辑（重力、碰撞）

        // 3. 执行待办指令 (必须在主线程执行)
        while (!commandQueue.isEmpty()) {
            String cmd = commandQueue.poll();
            if (cmd != null && !cmd.isEmpty()) {
                // 如果是指令（以/开头），通过 chat 发送，Minecraft 会自动处理
                // 如果是普通聊天，也会发送出去
                if (mc.getConnection() != null) {
                    // 如果不带 /，可以强制加上，或者允许直接发送聊天内容
                    // 这里假设用户通过 Socket 传来的就是完整的指令内容，例如 "/time set day"
                    // 如果想支持直接发聊天，可以去掉这个判断
                    if (!cmd.startsWith("/")) {
                        mc.getConnection().sendChat(cmd);
                    } else {
                        mc.getConnection().sendCommand(cmd.substring(1));
                    }
                }
            }
        }
        
        // 4. 处理方块查询
        if (pendingBlockQuery != null) {
            if (mc.level != null) {
                net.minecraft.world.level.block.state.BlockState state = mc.level.getBlockState(pendingBlockQuery);
                String blockName = net.minecraft.core.registries.BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
                String result = String.format("BLOCK %d %d %d %s %s", 
                    pendingBlockQuery.getX(), pendingBlockQuery.getY(), pendingBlockQuery.getZ(), 
                    blockName, state.toString());
                
                if (currentClientWriter != null) {
                    currentClientWriter.println(result);
                }
            }
            pendingBlockQuery = null; // 处理完毕，重置
        }

        // 处理手持物品查询
        if (shouldQueryHand) {
            shouldQueryHand = false;
            if (mc.player != null) {
                net.minecraft.world.item.ItemStack stack = mc.player.getMainHandItem();
                String itemName = net.minecraft.core.registries.BuiltInRegistries.ITEM.getKey(stack.getItem()).toString();
                int count = stack.getCount();
                // 获取物品的组件/NBT信息
                // stack.toString() 会返回 "数量 物品名" (例如 "1 diamond_sword")，这会导致数量和名称重复显示
                // 所以我们改用 getComponents() 来获取具体的物品数据 (如附魔、耐用度等)
                String info = stack.getComponents().toString();
                
                String result = String.format("HAND %s %d %s", itemName, count, info);
                
                if (currentClientWriter != null) {
                    currentClientWriter.println(result);
                }
            } else {
                if (currentClientWriter != null) {
                    currentClientWriter.println("FAIL: Player Not Found");
                }
            }
        }
        
        // 处理清空物品栏
        if (shouldClearInventory) {
            shouldClearInventory = false;
            if (mc.getConnection() != null) {
                mc.getConnection().sendCommand("clear");
                if (currentClientWriter != null) {
                    currentClientWriter.println("SUCCESS: Sent /clear command");
                }
            } else {
                if (currentClientWriter != null) {
                    currentClientWriter.println("FAIL: Not Connected to Server");
                }
            }
        }
        
        // 处理视线查询
        if (shouldQuerySight) {
            shouldQuerySight = false;
            double range = 100.0; // 检测范围
            net.minecraft.world.phys.HitResult hit = mc.player.pick(range, 0.0F, false);
            
            if (hit != null && hit.getType() == net.minecraft.world.phys.HitResult.Type.BLOCK) {
                net.minecraft.world.phys.BlockHitResult blockHit = (net.minecraft.world.phys.BlockHitResult) hit;
                net.minecraft.core.BlockPos pos = blockHit.getBlockPos();
                net.minecraft.world.level.block.state.BlockState state = mc.level.getBlockState(pos);
                String blockName = net.minecraft.core.registries.BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
                
                if (currentClientWriter != null) {
                    currentClientWriter.println("SIGHT " + blockName + " " + pos.getX() + " " + pos.getY() + " " + pos.getZ());
                }
            } else {
                if (currentClientWriter != null) {
                    currentClientWriter.println("FAIL: No Block in Sight (within " + range + " blocks)");
                }
            }
        }

        // 按名称查询实体位置与朝向（玩家游戏名或带自定义名的实体；以本地玩家为中心约 160 格）
        if (pendingEntityPoseQuery != null) {
            EntityPoseQuery query = pendingEntityPoseQuery;
            String qname = query.name;
            java.io.PrintWriter queryWriter = query.writer;
            pendingEntityPoseQuery = null;
            if (mc.level != null && mc.player != null) {
                Vec3 c = mc.player.position();
                AABB box = new AABB(c, c).inflate(160.0);
                List<Entity> matches = mc.level.getEntitiesOfClass(Entity.class, box,
                        e -> entityPoseNameMatches(e, qname));
                Entity best = null;
                double bestD = Double.MAX_VALUE;
                for (Entity e : matches) {
                    double d = e.distanceToSqr(mc.player);
                    if (d < bestD) {
                        bestD = d;
                        best = e;
                    }
                }
                if (best != null && queryWriter != null) {
                    String typeId = BuiltInRegistries.ENTITY_TYPE.getKey(best.getType()).toString();
                    queryWriter.println(String.format(Locale.US,
                            "ENTITY %s %s %.6f %.6f %.6f %.4f %.4f",
                            qname, typeId, best.getX(), best.getY(), best.getZ(),
                            best.getYRot(), best.getXRot()));
                } else if (queryWriter != null) {
                    queryWriter.println("FAIL: entity not found (not loaded or name mismatch): " + qname);
                }
            } else if (queryWriter != null) {
                queryWriter.println("FAIL: no level/player");
            }
        }
        
        // 处理周边3x3可达性查询
        if (shouldGetReachable) {
            shouldGetReachable = false;
            if (mc.player != null && mc.level != null) {
                net.minecraft.core.BlockPos center = mc.player.blockPosition();
                net.minecraft.core.Direction facing = mc.player.getDirection(); // NORTH, SOUTH, WEST, EAST
                
                // 定义相对偏移量 (Local Coordinates): 从前右开始顺时针一圈
                // 顺序: FrontRight, Right, BackRight, Back, BackLeft, Left, FrontLeft, Front
                int[][] offsets = new int[][] {
                    {1, 1},   // Front-Right
                    {1, 0},   // Right
                    {1, -1},  // Back-Right
                    {0, -1},  // Back
                    {-1, -1}, // Back-Left
                    {-1, 0},  // Left
                    {-1, 1},  // Front-Left
                    {0, 1}    // Front
                };
                
                // 根据朝向转换偏移量
                java.util.List<String> reachableList = new java.util.ArrayList<>();
                
                for (int[] offset : offsets) {
                    int dx = offset[0]; // Local Right/Left
                    int dz = offset[1]; // Local Front/Back
                    
                    int absX = 0;
                    int absZ = 0;
                    
                    switch (facing) {
                        case NORTH: // -Z is Front
                            absX = dx;
                            absZ = -dz;
                            break;
                        case SOUTH: // +Z is Front
                            absX = -dx; // Right is West (-X)
                            absZ = dz;
                            break;
                        case WEST: // -X is Front
                            absX = -dz;
                            absZ = -dx; // Right is North (-Z)
                            break;
                        case EAST: // +X is Front
                            absX = dz;
                            absZ = dx; // Right is South (+Z)
                            break;
                         case UP: case DOWN: // Should not happen for player facing usually, fallback to North
                            absX = dx;
                            absZ = -dz;
                            break;
                    }
                    
                    net.minecraft.core.BlockPos target = center.offset(absX, 0, absZ);
                    net.minecraft.world.level.block.state.BlockState state = mc.level.getBlockState(target);
                    
                    // 判断"可达且能放方块"：空气/可替换、有固体邻接、且放置后不与玩家 hitbox 相交
                    if (isPlaceable(mc.level, target, state, center, mc.player)) {
                        reachableList.add(target.getX() + " " + target.getY() + " " + target.getZ());
                    }
                }
                
                // 同时也检查中心点？题目说"3x3九宫格"，通常包括中心
                // 但"顺时针转动"通常指周围一圈。
                // 我们把中心点加在最后？或者不加？
                // 题目说: "返回可达点的坐标，以list的方式，最好可以按照从正前方开始顺时针转动的顺序返回"
                // 这强烈暗示是周围一圈。如果包含中心，通常是第一个或最后一个。
                // 既然已经在中心了，通常不需要"返回"它是可达的。
                // 这里只返回周围一圈的可达点。
                
                if (currentClientWriter != null) {
                    StringBuilder sb = new StringBuilder("REACHABLE");
                    for (String coords : reachableList) {
                        sb.append(" ").append(coords);
                    }
                    currentClientWriter.println(sb.toString());
                }
            } else {
                 if (currentClientWriter != null) {
                    currentClientWriter.println("FAIL: Player/Level Not Found");
                }
            }
        }

        // 5. 处理自动瞄准
        if (pendingAimPosRequest != null) {
            AimPosRequest req = pendingAimPosRequest;
            pendingAimPosRequest = null;
            LOGGER.debug("Processing AimPosRequest: " + req.x + ", " + req.y + ", " + req.z);

            if (mc.player != null) {
                // Target exact coordinates (no longer adding 0.5 for block center)
                net.minecraft.world.phys.Vec3 targetPos = new net.minecraft.world.phys.Vec3(req.x, req.y, req.z);
                net.minecraft.world.phys.Vec3 eyePos = mc.player.getEyePosition();
                double distSq = targetPos.distanceToSqr(eyePos);
                
                LOGGER.debug("DistanceSq: " + distSq + ", MaxDistSq: " + (req.maxDist * req.maxDist));

                if (distSq <= req.maxDist * req.maxDist) {
                    net.minecraft.world.phys.Vec3 diff = targetPos.subtract(eyePos);
                    double dist = diff.length();
                    double yaw = Math.toDegrees(Math.atan2(-diff.x, diff.z));
                    double pitch = Math.toDegrees(-Math.asin(diff.y / dist));

                    // Calculate spatial angle for FOV check
                    net.minecraft.world.phys.Vec3 lookVec = mc.player.getLookAngle();
                    net.minecraft.world.phys.Vec3 targetDir = diff.normalize();
                    double dot = lookVec.dot(targetDir);
                    double spatialAngle = Math.toDegrees(Math.acos(net.minecraft.util.Mth.clamp(dot, -1.0, 1.0)));

                    if (spatialAngle > req.maxAngle) {
                        if (currentClientWriter != null) {
                            currentClientWriter.println("FAIL: Out of View (Angle " + String.format("%.1f", spatialAngle) + " > " + req.maxAngle + ")");
                        }
                    } else {
                        float currentYaw = mc.player.getYRot();
                        float currentPitch = mc.player.getXRot();

                        float deltaYaw = net.minecraft.util.Mth.wrapDegrees((float)yaw - currentYaw);
                        float deltaPitch = (float)pitch - currentPitch;

                        targetYawRelative = deltaYaw;
                        targetPitchRelative = deltaPitch;
                        targetTurnDuration = req.duration;
                        shouldTurnRelative = true;

                        if (currentClientWriter != null) {
                            currentClientWriter.println("SUCCESS: Aiming at " + req.x + "," + req.y + "," + req.z + " (Angle " + String.format("%.1f", spatialAngle) + ")");
                        }
                    }
                } else {
                    if (currentClientWriter != null) {
                        currentClientWriter.println("FAIL: Target too far (" + String.format("%.1f", Math.sqrt(distSq)) + " > " + req.maxDist + ")");
                    }
                }
            }
        }

        if (pendingAimRequest != null) {
            AimRequest req = pendingAimRequest;
            pendingAimRequest = null; // 重置，防止重复处理

            if (mc.level != null && mc.player != null) {
                net.minecraft.core.BlockPos playerPos = mc.player.blockPosition();
                net.minecraft.core.BlockPos bestPos = null;
                double bestDistSq = Double.MAX_VALUE;
                
                int r = (int) Math.ceil(req.radius);
                // 遍历范围内方块
                for (int x = -r; x <= r; x++) {
                    for (int y = -r; y <= r; y++) {
                        for (int z = -r; z <= r; z++) {
                            net.minecraft.core.BlockPos pos = playerPos.offset(x, y, z);
                            // 检查距离
                            double distSq = pos.distToCenterSqr(mc.player.position()); // 或者 eyePosition
                            if (distSq > req.radius * req.radius) continue;

                            // 检查方块类型
                            net.minecraft.world.level.block.state.BlockState state = mc.level.getBlockState(pos);
                            String name = net.minecraft.core.registries.BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
                            
                            // 严格匹配：如果输入包含冒号，则全匹配；否则匹配冒号后的部分（针对省略 minecraft: 的情况）
                            // 但为了最严格，我们可以只允许 exact match，或者允许默认命名空间
                            // 这里我们保留目前的逻辑：name.equals(req.blockName) || name.endsWith(":" + req.blockName)
                            // 这样支持 "minecraft:gold_block" 和 "gold_block"
                            if (name.equals(req.blockName) || name.endsWith(":" + req.blockName)) {
                                if (distSq < bestDistSq) {
                                    bestDistSq = distSq;
                                    bestPos = pos;
                                }
                            }
                        }
                    }
                }

                if (bestPos != null) {
                    // 计算需要的 Yaw/Pitch
                    net.minecraft.world.phys.Vec3 eyePos = mc.player.getEyePosition();
                    net.minecraft.world.phys.Vec3 targetCenter = bestPos.getCenter();
                    net.minecraft.world.phys.Vec3 diff = targetCenter.subtract(eyePos);
                    
                    double dist = diff.length();
                    double yaw = Math.toDegrees(Math.atan2(-diff.x, diff.z)); // MC Yaw: -x, z
                    double pitch = Math.toDegrees(-Math.asin(diff.y / dist));

                    // 检查角度差 (FOV check)
                    float currentYaw = mc.player.getYRot();
                    float currentPitch = mc.player.getXRot();
                    
                    // 1. 计算需要的转动量 (用于执行)
                    float deltaYaw = net.minecraft.util.Mth.wrapDegrees((float)yaw - currentYaw);
                    float deltaPitch = (float)pitch - currentPitch;

                    // 2. 计算空间夹角 (用于判断 FOV) - 使用点积计算
                    net.minecraft.world.phys.Vec3 lookVec = mc.player.getLookAngle();
                    net.minecraft.world.phys.Vec3 targetDir = diff.normalize();
                    double dot = lookVec.dot(targetDir);
                    double spatialAngle = Math.toDegrees(Math.acos(net.minecraft.util.Mth.clamp(dot, -1.0, 1.0)));

                    if (spatialAngle > req.maxAngle) {
                         if (currentClientWriter != null) {
                            currentClientWriter.println("FAIL: Out of View (Angle " + String.format("%.1f", spatialAngle) + " > " + req.maxAngle + ")");
                        }
                    } else {
                        // 执行对准 (相对转动)
                        targetYawRelative = deltaYaw;
                        targetPitchRelative = deltaPitch;
                        targetTurnDuration = req.duration; // 传入持续时间
                        shouldTurnRelative = true;
                        
                        if (currentClientWriter != null) {
                            currentClientWriter.println("SUCCESS: Aimed at " + bestPos.toShortString() + " (Angle " + String.format("%.1f", spatialAngle) + ")");
                        }
                    }
                } else {
                    if (currentClientWriter != null) {
                        currentClientWriter.println("FAIL: Block Not Found");
                    }
                }
            }
        }

        // 6. 显示当前动作 (Action Bar)
        String status = "";
        if (currentAction != null && !currentAction.isEmpty()) {
            String agentLabel = (currentAgentName == null || currentAgentName.isEmpty() || "default".equalsIgnoreCase(currentAgentName)) ? "default" : currentAgentName;
            status += "§e[Puppet] (" + agentLabel + ") " + currentAction;
        }
        if (PositionRecorder.isRecording()) {
            status += " §c[REC]";
            PositionRecorder.recordTick(mc);
        }

        if (!status.isEmpty()) {
            mc.player.displayClientMessage(Component.literal(status), true);
        }
    }

    /**
     * 判断该格是否可放置方块：当前为空气/可替换，至少有一个固体邻接（有可依附的面），
     * 且放置后不与玩家 hitbox 相交（站在格子交界时，会占多格，这些格都不返回）。
     */
    private static boolean isPlaceable(net.minecraft.world.level.Level level, net.minecraft.core.BlockPos target,
                                      net.minecraft.world.level.block.state.BlockState state, net.minecraft.core.BlockPos playerBlock,
                                      net.minecraft.world.entity.Entity player) {
        if (target.equals(playerBlock)) return false; // 脚下格
        if (!state.isAir() && !state.canBeReplaced()) return false;
        // 若在该格放满方块，是否会与玩家碰撞（站在几格之间时 hitbox 会占多格）
        if (player != null) {
            net.minecraft.world.phys.AABB blockBox = new net.minecraft.world.phys.AABB(
                target.getX(), target.getY(), target.getZ(),
                target.getX() + 1, target.getY() + 1, target.getZ() + 1);
            if (blockBox.intersects(player.getBoundingBox())) return false;
        }
        for (net.minecraft.core.Direction d : net.minecraft.core.Direction.values()) {
            net.minecraft.world.level.block.state.BlockState neighbor = level.getBlockState(target.relative(d));
            if (!neighbor.isAir()) return true; // 有固体邻接即可放置
        }
        return false;
    }

    /** 尝试调用 startUseItem(InteractionHand)，1.21+ 可能为此签名。成功返回 true，否则 false。 */
    private boolean invokeStartUseItem(Minecraft mc) {
        try {
            java.lang.reflect.Method method = Minecraft.class.getDeclaredMethod("startUseItem", InteractionHand.class);
            method.setAccessible(true);
            method.invoke(mc, InteractionHand.MAIN_HAND);
            return true;
        } catch (NoSuchMethodException e) {
            return false;
        } catch (Exception e) {
            LOGGER.error("调用 startUseItem(Hand) 失败", e);
            return false;
        }
    }

    /** 调用无参 private 方法，成功返回 true，失败返回 false 并打日志。 */
    private boolean invokePrivateMethodReturn(Minecraft mc, String methodName) {
        try {
            java.lang.reflect.Method method = Minecraft.class.getDeclaredMethod(methodName);
            method.setAccessible(true);
            method.invoke(mc);
            return true;
        } catch (Exception e) {
            LOGGER.error("无法调用方法: " + methodName, e);
            return false;
        }
    }

    private void invokePrivateMethod(Minecraft mc, String methodName) {
        invokePrivateMethodReturn(mc, methodName);
    }

    // 玩家 Tick：客户端疾跑；服务端对命名假人按「实体+速度」驱动（与本体同物理）
    @SubscribeEvent
    public void onPlayerTick(PlayerTickEvent.Post event) {
        if (event.getEntity().level().isClientSide()) {
            if (isSprinting && event.getEntity() instanceof LocalPlayer player) {
                player.setSprinting(true);
            }
            return;
        }
        // 服务端：若当前 tick 的玩家是命名假人，则用速度/转角驱动（重力、碰撞由游戏处理）
        if (!(event.getEntity() instanceof ServerPlayer serverPlayer)) return;
        String name = serverPlayer.getGameProfile().getName();
        if (name == null) return;
        AgentMotionIntent intent = namedAgentIntents.get(name.toLowerCase(Locale.ROOT));
        if (intent == null) return;

        double fStep;
        double sStep;
        boolean wantsJump;
        synchronized (intent) {
            if (Math.abs(intent.deltaYaw) > 1e-6 || Math.abs(intent.deltaPitch) > 1e-6) {
                float yaw = net.minecraft.util.Mth.wrapDegrees((float) (serverPlayer.getYRot() + intent.deltaYaw));
                float pitch = net.minecraft.util.Mth.clamp((float) (serverPlayer.getXRot() + intent.deltaPitch), -90.0f, 90.0f);
                serverPlayer.setYRot(yaw);
                serverPlayer.setXRot(pitch);
                serverPlayer.setYHeadRot(yaw);
                serverPlayer.setYBodyRot(yaw);
                intent.deltaYaw = 0.0;
                intent.deltaPitch = 0.0;
            }
            if (Math.abs(intent.forwardRemaining) <= 1e-6 && Math.abs(intent.strafeRemaining) <= 1e-6 && !intent.wantsJump) {
                namedAgentIntents.remove(name.toLowerCase(Locale.ROOT), intent);
                Vec3 velocity = serverPlayer.getDeltaMovement();
                serverPlayer.setDeltaMovement(0.0, velocity.y, 0.0);
                return;
            }
            fStep = net.minecraft.util.Mth.clamp(intent.forwardRemaining, -NAMED_AGENT_STEP_PER_TICK, NAMED_AGENT_STEP_PER_TICK);
            sStep = net.minecraft.util.Mth.clamp(intent.strafeRemaining, -NAMED_AGENT_STEP_PER_TICK, NAMED_AGENT_STEP_PER_TICK);
            wantsJump = intent.wantsJump;
            intent.wantsJump = false;
            intent.forwardRemaining -= fStep;
            intent.strafeRemaining -= sStep;
        }

        double yawRad = Math.toRadians(serverPlayer.getYRot());
        double vx = -Math.sin(yawRad) * fStep + Math.cos(yawRad) * sStep;
        double vz = Math.cos(yawRad) * fStep + Math.sin(yawRad) * sStep;
        double vy = wantsJump ? 0.42 : serverPlayer.getDeltaMovement().y;
        serverPlayer.setDeltaMovement(vx, vy, vz);
        synchronized (intent) {
            if (Math.abs(intent.forwardRemaining) <= 1e-6 && Math.abs(intent.strafeRemaining) <= 1e-6 && !intent.wantsJump
                    && Math.abs(intent.deltaYaw) <= 1e-6 && Math.abs(intent.deltaPitch) <= 1e-6) {
                namedAgentIntents.remove(name.toLowerCase(Locale.ROOT), intent);
                Vec3 velocity = serverPlayer.getDeltaMovement();
                serverPlayer.setDeltaMovement(0.0, velocity.y, 0.0);
            }
        }
    }

    /** 第一人称下，取消渲染「当前相机所附着的那个假人」自身模型，避免挡住视野。 */
    @SubscribeEvent
    public void onRenderPlayerPre(RenderPlayerEvent.Pre event) {
        Entity hidden = hiddenCameraEntity;
        if (hidden == null) return;
        Minecraft mc = Minecraft.getInstance();
        if (mc.options.getCameraType() != net.minecraft.client.CameraType.FIRST_PERSON) return;
        if (event.getEntity() == hidden) {
            event.setCanceled(true);
        }
    }

    /** 与 query_entity 查询名匹配：玩家比游戏名；其它实体可比 CustomName 文本 */
    private static boolean entityPoseNameMatches(Entity entity, String want) {
        if (want == null || want.isEmpty()) return false;
        if (entity instanceof Player p && p.getGameProfile().getName() != null) {
            if (p.getGameProfile().getName().equalsIgnoreCase(want)) return true;
        }
        if (entity.hasCustomName() && entity.getCustomName() != null) {
            return entity.getCustomName().getString().equalsIgnoreCase(want);
        }
        return false;
    }
}