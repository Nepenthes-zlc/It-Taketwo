# Place command blocks for scene: elevator_crimson_black
setblock 89 -53 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute if block 95 -58 5 minecraft:crimson_pressure_plate[powered=true] run fill 94 -58 8 95 -54 8 minecraft:air"}
setblock 90 -53 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute unless block 95 -58 5 minecraft:crimson_pressure_plate[powered=true] run fill 94 -58 8 95 -54 8 minecraft:gilded_blackstone"}
