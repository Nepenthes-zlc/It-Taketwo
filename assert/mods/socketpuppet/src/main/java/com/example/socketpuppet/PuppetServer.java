package com.example.socketpuppet;

import com.mojang.logging.LogUtils;
import org.slf4j.Logger;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.Arrays;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class PuppetServer {
    private static final Logger LOGGER = LogUtils.getLogger();

    /** 所有已知动作指令的关键字，用于区分「代理名」与「指令」：首词不在集合内则视为代理名 */
    private static final Set<String> ACTION_KEYWORDS = Set.of(
            "w", "forward", "s", "backward", "a", "left", "d", "right", "jump", "sneak",
            "look", "look_rel", "turn", "stop", "attack", "left_click", "use", "right_click",
            "inventory", "e", "record", "cmd", "exec", "chat",
            "get_block", "query_block", "get_hand", "query_hand", "clear_inv", "clear_inventory",
            "f1", "f2", "screenshot", "aim", "grab", "get_sight", "get_reachable",
            "query_entity", "get_entity",
            "agent", "gamemode", "camera", "pov", "camera_entity", "hud");

    private static String normalizeAgentName(String name) {
        if (name == null || name.isEmpty()) return "default";
        String n = name.trim().toLowerCase();
        if (n.equals("default") || n.equals("player")) return "default";
        return name.trim();
    }

    /** 当前代理是否为「默认玩家」；否则为命名假人（当前用 /execute 控制，后续可接假人模组实体） */
    private static boolean isDefaultAgent() {
        String n = SocketPuppet.currentAgentName;
        if (n == null || n.isEmpty()) return true;
        String lower = n.trim().toLowerCase();
        return lower.equals("default") || lower.equals("player");
    }

    /** 命名假人移动：与玩家一致的速度逻辑，用 /execute as <name> run tp 实现，约 4.3 格/秒 */
    private static final double NAMED_AGENT_WALK_SPEED = 4.3;

    // ========== 统一逻辑：先算「意图」，再按当前目标应用（默认玩家 vs 命名假人） ==========

    /** 统一应用移动意图：默认玩家写 input 状态，命名假人写 namedAgent* 或 commandQueue */
    private static void applyMovement(float forward, float strafe, boolean jump, int tickDuration) {
        if (isDefaultAgent()) {
            SocketPuppet.targetForward = forward;
            SocketPuppet.targetStrafe = strafe;
            SocketPuppet.isJumping = jump;
            if (tickDuration > 0) SocketPuppet.movementTicksLeft = tickDuration;
            if (jump && tickDuration <= 0) SocketPuppet.movementTicksLeft = 2;
        } else {
            double dist = (tickDuration / 20.0) * NAMED_AGENT_WALK_SPEED;
            SocketPuppet.AgentMotionIntent intent = SocketPuppet.intentForNamedAgent(SocketPuppet.currentAgentName);
            synchronized (intent) {
                intent.forwardRemaining += forward * dist;
                intent.strafeRemaining += strafe * dist;
                if (jump) {
                    intent.wantsJump = true;
                }
            }
        }
    }

    /** 统一应用停止 */
    private static void applyStop() {
        SocketPuppet.targetForward = 0;
        SocketPuppet.targetStrafe = 0;
        SocketPuppet.isJumping = false;
        if (!isDefaultAgent() && SocketPuppet.currentAgentName != null) {
            SocketPuppet.namedAgentIntents.remove(SocketPuppet.currentAgentName.toLowerCase(java.util.Locale.ROOT));
        }
        SocketPuppet.currentAction = "Stopped";
    }

    /** 统一应用绝对视角：仅默认玩家时改本体视角；命名假人时用 /tp 改假人朝向（不碰本体） */
    private static void applyLookAbsolute(float yaw, float pitch, float lookDuration) {
        if (isDefaultAgent()) {
            SocketPuppet.targetYaw = yaw;
            SocketPuppet.targetPitch = pitch;
            SocketPuppet.targetLookDuration = lookDuration;
            SocketPuppet.shouldLookAbsolute = true;
        } else {
            // 命名假人：用指令设置假人朝向，不修改本地玩家视角
            SocketPuppet.commandQueue.add("/execute as " + SocketPuppet.currentAgentName + " at @s run tp @s ~ ~ ~ " + yaw + " " + pitch);
        }
    }

    /** 统一应用相对视角：默认玩家改本体视角；命名假人在服务端 tick 中改自身朝向 */
    private static void applyTurnRelative(float deltaYaw, float deltaPitch, float turnDuration) {
        if (isDefaultAgent()) {
            SocketPuppet.targetYawRelative = deltaYaw;
            SocketPuppet.targetPitchRelative = deltaPitch;
            SocketPuppet.targetTurnDuration = turnDuration;
            SocketPuppet.shouldTurnRelative = true;
        } else {
            SocketPuppet.AgentMotionIntent intent = SocketPuppet.intentForNamedAgent(SocketPuppet.currentAgentName);
            synchronized (intent) {
                intent.deltaYaw += deltaYaw;
                intent.deltaPitch += deltaPitch;
            }
        }
    }

    private final int port;
    private ServerSocket serverSocket;
    private final ScheduledExecutorService scheduler;
    private volatile boolean running;

    public PuppetServer(int port) {
        this.port = port;
        this.scheduler = Executors.newScheduledThreadPool(2);
        this.running = true;
    }

    public void start() throws IOException {
        serverSocket = new ServerSocket(port);
        LOGGER.debug("PuppetServer 监听端口: " + port);
        
        // 记录端口到文件
        PositionRecorder.writePort(port);

        while (running) {
            try {
                Socket clientSocket = serverSocket.accept();
                // 为每个连接开启新线程处理
                new Thread(() -> handleClient(clientSocket)).start();
            } catch (IOException e) {
                if (running) LOGGER.error("连接错误: " + e.getMessage());
            }
        }
    }

    private void handleClient(Socket socket) {
        // 客户端连接时，自动开始录制
        PositionRecorder.startRecording();
        LOGGER.debug("Client connected: " + socket.getRemoteSocketAddress());
        
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream()));
             java.io.PrintWriter writer = new java.io.PrintWriter(socket.getOutputStream(), true)) {
            
            // 将 writer 存入 SocketPuppet 以便在主线程使用
            SocketPuppet.currentClientWriter = writer;
            SocketPuppet.currentAgentName = "default";

            String line;
            while (running && (line = reader.readLine()) != null) {
                processCommand(line.trim(), writer);  // 保留原始大小写，便于 HUD 显示 agent_A 等
            }
        } catch (IOException e) {
            // 客户端断开
            LOGGER.debug("Client disconnected: " + socket.getRemoteSocketAddress());
        } finally {
            SocketPuppet.currentClientWriter = null;
            // 客户端断开时，自动停止录制
            PositionRecorder.stopRecording();
        }
    }

    private void processCommand(String command, java.io.PrintWriter writer) {
        String[] parts = command.split("\\s+");
        if (parts.length == 0) return;

        // 1) 显式设置代理: "agent <name>" 或 "agent <name> <子指令...>"
        if (parts[0].equalsIgnoreCase("agent")) {
            if (parts.length >= 2) {
                SocketPuppet.currentAgentName = normalizeAgentName(parts[1]);
                if (parts.length > 2) {
                    String rest = String.join(" ", Arrays.copyOfRange(parts, 2, parts.length));
                    processCommand(rest, writer);
                }
            }
            return;
        }

        // 2) 首词为代理名（非已知动作关键字）：如 "agenta w" -> 当前代理=agenta，执行 "w"
        if (!ACTION_KEYWORDS.contains(parts[0].toLowerCase())) {
            SocketPuppet.currentAgentName = normalizeAgentName(parts[0]);
            parts = Arrays.copyOfRange(parts, 1, parts.length);
            if (parts.length == 0) return;
        }

        String action = parts[0].toLowerCase();  // 指令关键字统一小写匹配

        // 更新 HUD 显示
        SocketPuppet.currentAction = action;

        float duration = 1.0f;
        if (parts.length > 1) {
            try { duration = Float.parseFloat(parts[1]); } catch (NumberFormatException ignored) {}
        }

        // 转换秒为 Ticks (1秒 = 20 Ticks)，至少 1 tick 保证短时长也能动
        int tickDuration = Math.max(1, (int) Math.ceil(duration * 20.0));

        switch (action) {
            case "w": case "forward":
                applyMovement(1.0f, 0.0f, false, tickDuration);
                break;
            case "s": case "backward":
                applyMovement(-1.0f, 0.0f, false, tickDuration);
                break;
            case "a": case "left":
                applyMovement(0.0f, 1.0f, false, tickDuration);
                break;
            case "d": case "right":
                applyMovement(0.0f, -1.0f, false, tickDuration);
                break;
            case "jump":
                applyMovement(0.0f, 0.0f, true, tickDuration > 0 ? tickDuration : 2);
                break;
            case "sneak":
                SocketPuppet.isSneaking = !SocketPuppet.isSneaking; break;
            case "look":
                if (parts.length >= 3) {
                    try {
                        float yaw = Float.parseFloat(parts[1]);
                        float pitch = Float.parseFloat(parts[2]);
                        float lookDuration = parts.length >= 4 ? Float.parseFloat(parts[3]) : 0.0f;
                        applyLookAbsolute(yaw, pitch, lookDuration);
                    } catch (Exception ignored) {}
                }
                break;
            case "look_rel": case "turn":
                if (parts.length >= 3) {
                    try {
                        float dy = Float.parseFloat(parts[1]);
                        float dp = Float.parseFloat(parts[2]);
                        float turnDuration = parts.length >= 4 ? Float.parseFloat(parts[3]) : 0.0f;
                        applyTurnRelative(dy, dp, turnDuration);
                    } catch (Exception ignored) {}
                }
                break;
            case "hud":
                // hud on|off|toggle — show/hide the "[Puppet] ..." action-bar overlay (off by default)
                if (parts.length >= 2) {
                    String v = parts[1].toLowerCase();
                    if (v.equals("on") || v.equals("1") || v.equals("true")) SocketPuppet.showStatusOverlay = true;
                    else if (v.equals("off") || v.equals("0") || v.equals("false")) SocketPuppet.showStatusOverlay = false;
                    else if (v.equals("toggle")) SocketPuppet.showStatusOverlay = !SocketPuppet.showStatusOverlay;
                }
                if (writer != null) writer.println("SUCCESS: hud overlay " + (SocketPuppet.showStatusOverlay ? "on" : "off"));
                break;
            case "stop":
                applyStop();
                break;
            case "gamemode":
                // gamemode <survival|adventure|creative|spectator> [目标名]
                // 无目标且当前为命名代理时，对当前假人执行，避免 /spectate 后假人为观察者模式穿墙
                if (parts.length >= 2) {
                    String mode = parts[1].toLowerCase();
                    if (mode.equals("0") || mode.equals("s") || mode.equals("survival")) mode = "survival";
                    else if (mode.equals("1") || mode.equals("c") || mode.equals("creative")) mode = "creative";
                    else if (mode.equals("2") || mode.equals("a") || mode.equals("adventure")) mode = "adventure";
                    else if (mode.equals("3") || mode.equals("sp") || mode.equals("spectator")) mode = "spectator";
                    String target = parts.length >= 3 ? parts[2] : (isDefaultAgent() ? null : SocketPuppet.currentAgentName);
                    String cmd = target != null ? "/gamemode " + mode + " " + target : "/gamemode " + mode;
                    SocketPuppet.commandQueue.add(cmd);
                    SocketPuppet.currentAction = "Gamemode: " + mode + (target != null ? " " + target : "");
                }
                break;
            case "attack": case "left_click":
                SocketPuppet.shouldLeftClick = true; break;
            case "use": case "right_click":
                SocketPuppet.shouldRightClick = true; break;
            case "inventory": case "e":
                SocketPuppet.shouldOpenInventory = true; break;
            case "record":
                if (parts.length > 1 && parts[1].equals("start")) {
                    PositionRecorder.startRecording();
                    SocketPuppet.currentAction = "Recording Started";
                } else if (parts.length > 1 && parts[1].equals("stop")) {
                    PositionRecorder.stopRecording();
                    SocketPuppet.currentAction = "Recording Stopped";
                }
                break;
            case "cmd": case "exec":
                // 将后续的所有部分重新组合成一个完整的指令字符串
                // 例如: "cmd time set day" -> "/time set day"
                if (parts.length > 1) {
                    StringBuilder sb = new StringBuilder();
                    // 判断第一个参数是否以 / 开头，如果没有则自动补上（针对指令）
                    // 但如果是聊天内容，可能不需要 /
                    // 这里我们约定：如果使用 "cmd"，默认是想执行指令，自动补 /
                    // 如果已经是 / 开头，则保留
                    String firstArg = parts[1];
                    if (!firstArg.startsWith("/")) {
                        sb.append("/");
                    }
                    
                    for (int i = 1; i < parts.length; i++) {
                        sb.append(parts[i]).append(" ");
                    }
                    String fullCmd = sb.toString().trim();
                    SocketPuppet.commandQueue.add(fullCmd);
                    SocketPuppet.currentAction = "Exec: " + fullCmd;
                }
                break;
            case "chat":
                // 发送普通聊天消息，不带 /
                if (parts.length > 1) {
                    StringBuilder sb = new StringBuilder();
                    for (int i = 1; i < parts.length; i++) {
                        sb.append(parts[i]).append(" ");
                    }
                    String chatMsg = sb.toString().trim();
                    SocketPuppet.commandQueue.add(chatMsg);
                    SocketPuppet.currentAction = "Chat: " + chatMsg;
                }
                break;
            case "get_block": case "query_block":
                // 查询方块信息: get_block x y z
                if (parts.length >= 4) {
                    try {
                        int x = Integer.parseInt(parts[1]);
                        int y = Integer.parseInt(parts[2]);
                        int z = Integer.parseInt(parts[3]);
                        SocketPuppet.pendingBlockQuery = new net.minecraft.core.BlockPos(x, y, z);
                    } catch (NumberFormatException e) {
                        SocketPuppet.currentAction = "Query Error: Invalid Coords";
                    }
                }
                break;
            case "get_hand": case "query_hand":
                SocketPuppet.shouldQueryHand = true;
                SocketPuppet.currentAction = "Querying Hand";
                break;
            case "clear_inv": case "clear_inventory":
                SocketPuppet.shouldClearInventory = true;
                SocketPuppet.currentAction = "Clearing Inventory";
                break;
            case "f1":
                SocketPuppet.toggleF1 = true; break;
            case "f2": case "screenshot":
                SocketPuppet.toggleF2 = true; break;
            case "camera":
                if (parts.length >= 2) {
                    String cameraType = parts[1].toLowerCase();
                    if (!cameraType.equals("third_person_back") && !cameraType.equals("third_person_front")) {
                        cameraType = "first_person";
                    }
                    SocketPuppet.pendingCameraType = cameraType;
                    SocketPuppet.currentAction = "Camera: " + cameraType;
                }
                break;
            case "pov": case "camera_entity":
                if (parts.length >= 2) {
                    SocketPuppet.pendingCameraEntityName = normalizeAgentName(parts[1]);
                    SocketPuppet.pendingCameraType = "first_person";
                    SocketPuppet.currentAction = "POV request: " + parts[1];
                }
                break;
            case "aim":
                // Check if first arg is a coordinate (number) or block name (string)
                if (parts.length >= 2) {
                    boolean isCoordinate = false;
                    try {
                        Double.parseDouble(parts[1]);
                        isCoordinate = true;
                    } catch (NumberFormatException e) {
                        isCoordinate = false;
                    }

                    if (isCoordinate) {
                        // aim <x> <y> <z> <max_dist> [max_angle] [duration]
                        if (parts.length >= 5) {
                            try {
                                double x = Double.parseDouble(parts[1]);
                                double y = Double.parseDouble(parts[2]);
                                double z = Double.parseDouble(parts[3]);
                                double maxDist = Double.parseDouble(parts[4]);
                                
                                double maxAngle = 360.0; // Default to allow any angle
                                if (parts.length >= 6) {
                                    maxAngle = Double.parseDouble(parts[5]);
                                }
                                
                                float aimPosDuration = 0.0f;
                                if (parts.length >= 7) {
                                    aimPosDuration = Float.parseFloat(parts[6]);
                                }
                                
                                SocketPuppet.pendingAimPosRequest = new SocketPuppet.AimPosRequest(x, y, z, maxDist, aimPosDuration, maxAngle);
                                SocketPuppet.currentAction = "Aiming at Pos";
                            } catch (Exception e) {
                                SocketPuppet.currentAction = "Aim Pos Error: Invalid Args";
                            }
                        }
                    } else {
                        // aim <block_id> <radius> [max_angle] [duration]
                        if (parts.length >= 3) {
                            try {
                                String blockName = parts[1];
                                double radius = Double.parseDouble(parts[2]);
                                double maxAngle = 90.0; // 默认 90 度 FOV
                                if (parts.length >= 4) {
                                    maxAngle = Double.parseDouble(parts[3]);
                                }
                                float aimDuration = 0.0f; // 默认瞬间瞄准
                                if (parts.length >= 5) {
                                    aimDuration = Float.parseFloat(parts[4]);
                                }
                                SocketPuppet.pendingAimRequest = new SocketPuppet.AimRequest(blockName, radius, maxAngle, aimDuration);
                                SocketPuppet.currentAction = "Aiming: " + blockName;
                            } catch (Exception e) {
                                SocketPuppet.currentAction = "Aim Error: Invalid Args";
                            }
                        }
                    }
                }
                break;
            case "grab":
                SocketPuppet.shouldGrab = true;
                SocketPuppet.currentAction = "Grabbing Block";
                break;
            case "get_sight":
                SocketPuppet.shouldQuerySight = true;
                SocketPuppet.currentAction = "Querying Sight";
                break;
            case "query_entity": case "get_entity":
                if (parts.length >= 2) {
                    SocketPuppet.pendingEntityPoseQuery = new SocketPuppet.EntityPoseQuery(parts[1], writer);
                    SocketPuppet.currentAction = "Query Entity: " + parts[1];
                } else if (writer != null) {
                    writer.println("FAIL: query_entity <name>");
                }
                break;
            case "get_reachable":
                SocketPuppet.shouldGetReachable = true;
                SocketPuppet.currentAction = "Querying Reachable";
                break;
        }

        // 对「无异步回复」的指令立即回复 OK，避免客户端 wait_for_response 长时间阻塞
        Set<String> asyncReplyActions = Set.of(
                "get_block", "query_block", "get_hand", "query_hand",
                "get_sight", "get_reachable", "grab", "aim",
                "clear_inv", "clear_inventory",
                "query_entity", "get_entity");
        if (!asyncReplyActions.contains(action) && writer != null) {
            writer.println("OK");
        }

        // 自动重置 HUD 文本 (不再需要 scheduleReset)
        // HUD 更新由 ClientTick 根据 movementTicksLeft 处理，或者保持常亮
        // 但如果不是移动指令，我们还是希望它显示一会儿
        if (!action.equals("stop") && !action.equals("sneak") && !action.equals("look")) {
             // 简单的延时重置 HUD 文本，这个可以用原来的 scheduler，因为这只影响显示，不影响物理逻辑
             if (duration > 0) scheduleReset(() -> SocketPuppet.currentAction = "Waiting...", duration);
        }
    }

    private void scheduleReset(Runnable task, float seconds) {
        if (seconds > 0) scheduler.schedule(task, (long) (seconds * 1000), TimeUnit.MILLISECONDS);
    }
}