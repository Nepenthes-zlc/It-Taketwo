# Tick logic for scene: elevator_wood_lodge_green
execute if block 28 -58 5 minecraft:spruce_pressure_plate[powered=true] run fill 27 -58 8 29 -56 8 minecraft:air
execute unless block 28 -58 5 minecraft:spruce_pressure_plate[powered=true] run fill 27 -58 8 29 -56 8 minecraft:copper_block
