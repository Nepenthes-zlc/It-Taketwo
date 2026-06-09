# Place command blocks for scene: elevator_deepslate_orange
setblock 45 -55 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute if block 49 -58 4 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 48 -58 6 49 -55 6 minecraft:air"}
setblock 46 -55 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute unless block 49 -58 4 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 48 -58 6 49 -55 6 minecraft:polished_blackstone_bricks"}
