# Tick logic for scene: tier_elevator_hard_09
execute if block 852 -58 6 minecraft:mangrove_pressure_plate[powered=true] run fill 850 -58 12 850 -56 12 minecraft:air
execute if block 852 -58 7 minecraft:mangrove_pressure_plate[powered=true] run fill 850 -58 12 850 -56 12 minecraft:air
execute if block 853 -58 6 minecraft:mangrove_pressure_plate[powered=true] run fill 850 -58 12 850 -56 12 minecraft:air
execute if block 853 -58 7 minecraft:mangrove_pressure_plate[powered=true] run fill 850 -58 12 850 -56 12 minecraft:air
execute unless block 852 -58 6 minecraft:mangrove_pressure_plate[powered=true] unless block 852 -58 7 minecraft:mangrove_pressure_plate[powered=true] unless block 853 -58 6 minecraft:mangrove_pressure_plate[powered=true] unless block 853 -58 7 minecraft:mangrove_pressure_plate[powered=true] run fill 850 -58 12 850 -56 12 minecraft:green_concrete
