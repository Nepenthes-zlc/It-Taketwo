package com.example.socketpuppet;

import net.minecraft.client.Minecraft;
import net.minecraft.world.phys.Vec3;
import org.slf4j.Logger;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

public class PositionRecorder {
    private static final Logger LOGGER = SocketPuppet.LOGGER;
    private static volatile boolean isRecording = false;
    private static volatile BufferedWriter writer;
    private static File baseDir;
    
    // 初始化基础目录
    private static void ensureBaseDir() {
        if (baseDir == null) {
            baseDir = new File(Minecraft.getInstance().gameDirectory, "socketpuppet_data");
        }
        if (!baseDir.exists()) {
            baseDir.mkdirs();
        }
    }

    public static void startRecording() {
        if (isRecording) return;

        try {
            ensureBaseDir();

            // 坐标日志文件 (固定名称，追加模式)
            File outputFile = new File(baseDir, "recording.csv");
            boolean fileExists = outputFile.exists();
            
            // 使用追加模式 (true)
            writer = new BufferedWriter(new FileWriter(outputFile, true));
            
            // 如果是新文件，写入 CSV 头 (移除 screenshot_file)
            if (!fileExists) {
                writer.write("timestamp,x,y,z,yaw,pitch");
                writer.newLine();
            }

            isRecording = true;
            LOGGER.debug("Started recording to: " + baseDir.getAbsolutePath());
        } catch (IOException e) {
            LOGGER.error("Failed to start recording", e);
        }
    }

    public static void stopRecording() {
        if (!isRecording) return;

        try {
            if (writer != null) {
                writer.close();
                writer = null;
            }
            isRecording = false;
            LOGGER.debug("Stopped recording.");
        } catch (IOException e) {
            LOGGER.error("Failed to stop recording", e);
        }
    }

    public static void recordTick(Minecraft mc) {
        // Snapshot the writer reference: stopRecording() may null the field from
        // another thread between this check and the writes below, which previously
        // crashed the client with an NPE during episode resets.
        BufferedWriter w = writer;
        if (!isRecording || mc.player == null || w == null) return;

        try {
            double x = mc.player.getX();
            double y = mc.player.getY();
            double z = mc.player.getZ();

            // 规范化 Yaw 到 -180 到 180 (Minecraft F3 默认显示)
            float yRot = mc.player.getYRot() % 360.0f;
            if (yRot > 180.0f) yRot -= 360.0f;
            if (yRot < -180.0f) yRot += 360.0f;

            float xRot = mc.player.getXRot();

            String time = LocalDateTime.now().format(DateTimeFormatter.ofPattern("HH:mm:ss.SSS"));

            // 格式: timestamp, x, y, z, yaw, pitch
            String line = String.format("%s,%.3f,%.3f,%.3f,%.3f,%.3f",
                    time, x, y, z, yRot, xRot);

            w.write(line);
            w.newLine();
            w.flush();
        } catch (IOException e) {
            LOGGER.error("Error writing position", e);
            stopRecording();
        }
    }

    public static void writePort(int port) {
        try {
            ensureBaseDir();
            File portFile = new File(baseDir, "port.txt");
            try (BufferedWriter bw = new BufferedWriter(new FileWriter(portFile))) {
                bw.write(String.valueOf(port));
            }
            LOGGER.debug("Port written to file: " + port);
        } catch (IOException e) {
            LOGGER.error("Failed to write port file", e);
        }
    }

    public static boolean isRecording() {
        return isRecording;
    }
}
