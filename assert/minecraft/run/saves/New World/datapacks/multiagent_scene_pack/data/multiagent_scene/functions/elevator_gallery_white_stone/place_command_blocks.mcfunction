# Place command blocks for scene: elevator_gallery_white_stone
setblock 1 -55 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute if block 6 -58 5 minecraft:stone_pressure_plate[powered=true] run fill 5 -58 7 6 -56 7 minecraft:air"}
setblock 2 -55 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute unless block 6 -58 5 minecraft:stone_pressure_plate[powered=true] run fill 5 -58 7 6 -56 7 minecraft:iron_block"}
