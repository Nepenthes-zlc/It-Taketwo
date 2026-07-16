# Tick logic for scene: tier_elevator_hard_01
execute if block 611 -58 6 minecraft:stone_pressure_plate[powered=true] run fill 611 -58 12 611 -56 12 minecraft:air
execute if block 611 -58 7 minecraft:stone_pressure_plate[powered=true] run fill 611 -58 12 611 -56 12 minecraft:air
execute if block 612 -58 6 minecraft:stone_pressure_plate[powered=true] run fill 611 -58 12 611 -56 12 minecraft:air
execute if block 612 -58 7 minecraft:stone_pressure_plate[powered=true] run fill 611 -58 12 611 -56 12 minecraft:air
execute unless block 611 -58 6 minecraft:stone_pressure_plate[powered=true] unless block 611 -58 7 minecraft:stone_pressure_plate[powered=true] unless block 612 -58 6 minecraft:stone_pressure_plate[powered=true] unless block 612 -58 7 minecraft:stone_pressure_plate[powered=true] run fill 611 -58 12 611 -56 12 minecraft:red_concrete
