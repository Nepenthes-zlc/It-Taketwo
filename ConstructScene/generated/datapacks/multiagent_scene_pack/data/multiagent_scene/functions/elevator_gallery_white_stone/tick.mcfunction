# Tick logic for scene: elevator_gallery_white_stone
execute if block 6 -58 5 minecraft:stone_pressure_plate[powered=true] run fill 5 -58 7 6 -56 7 minecraft:air
execute unless block 6 -58 5 minecraft:stone_pressure_plate[powered=true] run fill 5 -58 7 6 -56 7 minecraft:iron_block
