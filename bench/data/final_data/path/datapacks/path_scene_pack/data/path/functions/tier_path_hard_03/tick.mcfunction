# Tick logic for scene: tier_path_hard_03
execute if block 1571 -57 8 minecraft:oak_pressure_plate[powered=true] run fill 1570 -58 12 1571 -58 18 minecraft:blue_concrete
execute if block 1571 -57 9 minecraft:oak_pressure_plate[powered=true] run fill 1570 -58 12 1571 -58 18 minecraft:blue_concrete
execute if block 1572 -57 8 minecraft:oak_pressure_plate[powered=true] run fill 1570 -58 12 1571 -58 18 minecraft:blue_concrete
execute if block 1572 -57 9 minecraft:oak_pressure_plate[powered=true] run fill 1570 -58 12 1571 -58 18 minecraft:blue_concrete
execute unless block 1571 -57 8 minecraft:oak_pressure_plate[powered=true] unless block 1571 -57 9 minecraft:oak_pressure_plate[powered=true] unless block 1572 -57 8 minecraft:oak_pressure_plate[powered=true] unless block 1572 -57 9 minecraft:oak_pressure_plate[powered=true] run fill 1570 -58 12 1571 -58 18 minecraft:air
