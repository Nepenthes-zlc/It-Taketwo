# Place command blocks for scene: elevator_warped_lapis
setblock 135 -53 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute if block 143 -58 5 minecraft:warped_pressure_plate[powered=true] run fill 141 -58 9 143 -54 9 minecraft:air"}
setblock 136 -53 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute unless block 143 -58 5 minecraft:warped_pressure_plate[powered=true] run fill 141 -58 9 143 -54 9 minecraft:lapis_block"}
