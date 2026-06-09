# Place command blocks for scene: elevator_pink_cherry
setblock 111 -55 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute if block 118 -58 5 minecraft:cherry_pressure_plate[powered=true] run fill 116 -58 7 119 -56 7 minecraft:air"}
setblock 112 -55 1 minecraft:repeating_command_block[facing=east]{auto:1b,Command:"execute unless block 118 -58 5 minecraft:cherry_pressure_plate[powered=true] run fill 116 -58 7 119 -56 7 minecraft:purpur_block"}
