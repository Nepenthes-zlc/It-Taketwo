# Tick logic for scene: tier_elevator_medium_01
execute if block 310 -58 7 minecraft:stone_pressure_plate[powered=true] run fill 310 -58 12 311 -56 12 minecraft:air
execute if block 310 -58 8 minecraft:stone_pressure_plate[powered=true] run fill 310 -58 12 311 -56 12 minecraft:air
execute if block 310 -58 9 minecraft:stone_pressure_plate[powered=true] run fill 310 -58 12 311 -56 12 minecraft:air
execute if block 311 -58 7 minecraft:stone_pressure_plate[powered=true] run fill 310 -58 12 311 -56 12 minecraft:air
execute if block 311 -58 8 minecraft:stone_pressure_plate[powered=true] run fill 310 -58 12 311 -56 12 minecraft:air
execute if block 311 -58 9 minecraft:stone_pressure_plate[powered=true] run fill 310 -58 12 311 -56 12 minecraft:air
execute if block 312 -58 7 minecraft:stone_pressure_plate[powered=true] run fill 310 -58 12 311 -56 12 minecraft:air
execute if block 312 -58 8 minecraft:stone_pressure_plate[powered=true] run fill 310 -58 12 311 -56 12 minecraft:air
execute if block 312 -58 9 minecraft:stone_pressure_plate[powered=true] run fill 310 -58 12 311 -56 12 minecraft:air
execute unless block 310 -58 7 minecraft:stone_pressure_plate[powered=true] unless block 310 -58 8 minecraft:stone_pressure_plate[powered=true] unless block 310 -58 9 minecraft:stone_pressure_plate[powered=true] unless block 311 -58 7 minecraft:stone_pressure_plate[powered=true] unless block 311 -58 8 minecraft:stone_pressure_plate[powered=true] unless block 311 -58 9 minecraft:stone_pressure_plate[powered=true] unless block 312 -58 7 minecraft:stone_pressure_plate[powered=true] unless block 312 -58 8 minecraft:stone_pressure_plate[powered=true] unless block 312 -58 9 minecraft:stone_pressure_plate[powered=true] run fill 310 -58 12 311 -56 12 minecraft:red_concrete
