# Tick logic for scene: tier_elevator_hard_04
execute if block 702 -58 4 minecraft:spruce_pressure_plate[powered=true] run fill 701 -58 11 701 -56 11 minecraft:air
execute if block 702 -58 5 minecraft:spruce_pressure_plate[powered=true] run fill 701 -58 11 701 -56 11 minecraft:air
execute if block 703 -58 4 minecraft:spruce_pressure_plate[powered=true] run fill 701 -58 11 701 -56 11 minecraft:air
execute if block 703 -58 5 minecraft:spruce_pressure_plate[powered=true] run fill 701 -58 11 701 -56 11 minecraft:air
execute unless block 702 -58 4 minecraft:spruce_pressure_plate[powered=true] unless block 702 -58 5 minecraft:spruce_pressure_plate[powered=true] unless block 703 -58 4 minecraft:spruce_pressure_plate[powered=true] unless block 703 -58 5 minecraft:spruce_pressure_plate[powered=true] run fill 701 -58 11 701 -56 11 minecraft:lime_concrete
