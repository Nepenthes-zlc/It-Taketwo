# Tick logic for scene: tier_elevator_hard_03
execute if block 670 -58 6 minecraft:oak_pressure_plate[powered=true] run fill 670 -58 12 670 -56 12 minecraft:air
execute if block 670 -58 7 minecraft:oak_pressure_plate[powered=true] run fill 670 -58 12 670 -56 12 minecraft:air
execute if block 671 -58 6 minecraft:oak_pressure_plate[powered=true] run fill 670 -58 12 670 -56 12 minecraft:air
execute if block 671 -58 7 minecraft:oak_pressure_plate[powered=true] run fill 670 -58 12 670 -56 12 minecraft:air
execute unless block 670 -58 6 minecraft:oak_pressure_plate[powered=true] unless block 670 -58 7 minecraft:oak_pressure_plate[powered=true] unless block 671 -58 6 minecraft:oak_pressure_plate[powered=true] unless block 671 -58 7 minecraft:oak_pressure_plate[powered=true] run fill 670 -58 12 670 -56 12 minecraft:yellow_concrete
