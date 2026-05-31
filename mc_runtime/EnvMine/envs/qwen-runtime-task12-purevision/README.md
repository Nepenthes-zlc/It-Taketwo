# TickGate Runtime Minimal Template

This directory is the batch-launch template for Minecraft runtime instances. It is intentionally not a Gradle mod development project.

Contents:
- `launch_tickgate.sh`: starts NeoForge/Minecraft directly with Java.
- `launch/`: cached NeoForge/Minecraft argument files and classpath file. It uses the NeoForge dev launch target because the current Carpet mod is built against deobfuscated class names, but no Gradle task is run at startup.
- `libraries/`: tiny Maven-layout symlink set for the Minecraft/NeoForge system jars.
- `run/mods/`: only the runtime mods: TickGate, SocketPuppet, and Carpet.
- `run/config/tickgate-common.toml`: TickGate IPC and auto-world config.
- `run/saves/New World/`: the prepared world with the generated scene datapack.

Do not copy runtime state into this template, especially `run/logs/`, `run/socketpuppet_data/`, or world `session.lock` files. Batch workers should clone this directory, then patch each clone's `run/config/tickgate-common.toml` to use a unique TickGate IPC port.