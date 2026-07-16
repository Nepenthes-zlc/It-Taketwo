# Tick logic for scene: tier_path_hard_01
execute if block 1511 -57 8 minecraft:stone_pressure_plate[powered=true] run fill 1510 -58 12 1511 -58 18 minecraft:lime_concrete
execute if block 1511 -57 9 minecraft:stone_pressure_plate[powered=true] run fill 1510 -58 12 1511 -58 18 minecraft:lime_concrete
execute if block 1512 -57 8 minecraft:stone_pressure_plate[powered=true] run fill 1510 -58 12 1511 -58 18 minecraft:lime_concrete
execute if block 1512 -57 9 minecraft:stone_pressure_plate[powered=true] run fill 1510 -58 12 1511 -58 18 minecraft:lime_concrete
execute unless block 1511 -57 8 minecraft:stone_pressure_plate[powered=true] unless block 1511 -57 9 minecraft:stone_pressure_plate[powered=true] unless block 1512 -57 8 minecraft:stone_pressure_plate[powered=true] unless block 1512 -57 9 minecraft:stone_pressure_plate[powered=true] run fill 1510 -58 12 1511 -58 18 minecraft:air
