# Tick logic for scene: elevator_pink_cherry
execute if block 118 -58 5 minecraft:cherry_pressure_plate[powered=true] run fill 116 -58 7 119 -56 7 minecraft:air
execute unless block 118 -58 5 minecraft:cherry_pressure_plate[powered=true] run fill 116 -58 7 119 -56 7 minecraft:purpur_block
