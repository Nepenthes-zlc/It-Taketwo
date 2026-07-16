# Tick logic for scene: tier_path_hard_09
execute if block 1751 -57 8 minecraft:mangrove_pressure_plate[powered=true] run fill 1750 -58 12 1751 -58 18 minecraft:purple_concrete
execute if block 1751 -57 9 minecraft:mangrove_pressure_plate[powered=true] run fill 1750 -58 12 1751 -58 18 minecraft:purple_concrete
execute if block 1752 -57 8 minecraft:mangrove_pressure_plate[powered=true] run fill 1750 -58 12 1751 -58 18 minecraft:purple_concrete
execute if block 1752 -57 9 minecraft:mangrove_pressure_plate[powered=true] run fill 1750 -58 12 1751 -58 18 minecraft:purple_concrete
execute unless block 1751 -57 8 minecraft:mangrove_pressure_plate[powered=true] unless block 1751 -57 9 minecraft:mangrove_pressure_plate[powered=true] unless block 1752 -57 8 minecraft:mangrove_pressure_plate[powered=true] unless block 1752 -57 9 minecraft:mangrove_pressure_plate[powered=true] run fill 1750 -58 12 1751 -58 18 minecraft:air
