# Tick logic for scene: elevator_warped_lapis
execute if block 143 -58 5 minecraft:warped_pressure_plate[powered=true] run fill 141 -58 9 143 -54 9 minecraft:air
execute unless block 143 -58 5 minecraft:warped_pressure_plate[powered=true] run fill 141 -58 9 143 -54 9 minecraft:lapis_block
