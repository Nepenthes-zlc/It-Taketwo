# Place command blocks for scene: elevator_aqua_prismarine
setblock 64 -54 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute if block 71 -58 5 minecraft:birch_pressure_plate[powered=true] run fill 70 -58 9 72 -55 9 minecraft:air"}
setblock 65 -54 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute unless block 71 -58 5 minecraft:birch_pressure_plate[powered=true] run fill 70 -58 9 72 -55 9 minecraft:quartz_block"}
