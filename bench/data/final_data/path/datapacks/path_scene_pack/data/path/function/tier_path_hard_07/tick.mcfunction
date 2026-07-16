# Tick logic for scene: tier_path_hard_07
execute if block 1691 -57 8 minecraft:acacia_pressure_plate[powered=true] run fill 1690 -58 12 1691 -58 18 minecraft:green_concrete
execute if block 1691 -57 9 minecraft:acacia_pressure_plate[powered=true] run fill 1690 -58 12 1691 -58 18 minecraft:green_concrete
execute if block 1692 -57 8 minecraft:acacia_pressure_plate[powered=true] run fill 1690 -58 12 1691 -58 18 minecraft:green_concrete
execute if block 1692 -57 9 minecraft:acacia_pressure_plate[powered=true] run fill 1690 -58 12 1691 -58 18 minecraft:green_concrete
execute unless block 1691 -57 8 minecraft:acacia_pressure_plate[powered=true] unless block 1691 -57 9 minecraft:acacia_pressure_plate[powered=true] unless block 1692 -57 8 minecraft:acacia_pressure_plate[powered=true] unless block 1692 -57 9 minecraft:acacia_pressure_plate[powered=true] run fill 1690 -58 12 1691 -58 18 minecraft:air
