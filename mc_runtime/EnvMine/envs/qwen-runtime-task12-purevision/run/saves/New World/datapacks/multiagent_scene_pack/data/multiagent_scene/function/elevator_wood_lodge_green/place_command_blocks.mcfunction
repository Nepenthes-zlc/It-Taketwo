# Place command blocks for scene: elevator_wood_lodge_green
setblock 22 -54 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute if block 28 -58 5 minecraft:spruce_pressure_plate[powered=true] run fill 27 -58 8 29 -56 8 minecraft:air"}
setblock 23 -54 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute unless block 28 -58 5 minecraft:spruce_pressure_plate[powered=true] run fill 27 -58 8 29 -56 8 minecraft:copper_block"}
