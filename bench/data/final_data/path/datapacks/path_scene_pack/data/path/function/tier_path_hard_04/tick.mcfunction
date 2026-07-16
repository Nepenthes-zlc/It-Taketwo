# Tick logic for scene: tier_path_hard_04
execute if block 1601 -57 8 minecraft:spruce_pressure_plate[powered=true] run fill 1600 -58 12 1601 -58 18 minecraft:magenta_concrete
execute if block 1601 -57 9 minecraft:spruce_pressure_plate[powered=true] run fill 1600 -58 12 1601 -58 18 minecraft:magenta_concrete
execute if block 1602 -57 8 minecraft:spruce_pressure_plate[powered=true] run fill 1600 -58 12 1601 -58 18 minecraft:magenta_concrete
execute if block 1602 -57 9 minecraft:spruce_pressure_plate[powered=true] run fill 1600 -58 12 1601 -58 18 minecraft:magenta_concrete
execute unless block 1601 -57 8 minecraft:spruce_pressure_plate[powered=true] unless block 1601 -57 9 minecraft:spruce_pressure_plate[powered=true] unless block 1602 -57 8 minecraft:spruce_pressure_plate[powered=true] unless block 1602 -57 9 minecraft:spruce_pressure_plate[powered=true] run fill 1600 -58 12 1601 -58 18 minecraft:air
