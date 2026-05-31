# Tick logic for scene: elevator_aqua_prismarine
execute if block 71 -58 5 minecraft:birch_pressure_plate[powered=true] run fill 70 -58 9 72 -55 9 minecraft:air
execute unless block 71 -58 5 minecraft:birch_pressure_plate[powered=true] run fill 70 -58 9 72 -55 9 minecraft:quartz_block
