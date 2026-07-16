# Tick logic for scene: tier_elevator_hard_07
execute if block 793 -58 6 minecraft:acacia_pressure_plate[powered=true] run fill 791 -58 12 791 -56 12 minecraft:air
execute if block 793 -58 7 minecraft:acacia_pressure_plate[powered=true] run fill 791 -58 12 791 -56 12 minecraft:air
execute if block 794 -58 6 minecraft:acacia_pressure_plate[powered=true] run fill 791 -58 12 791 -56 12 minecraft:air
execute if block 794 -58 7 minecraft:acacia_pressure_plate[powered=true] run fill 791 -58 12 791 -56 12 minecraft:air
execute unless block 793 -58 6 minecraft:acacia_pressure_plate[powered=true] unless block 793 -58 7 minecraft:acacia_pressure_plate[powered=true] unless block 794 -58 6 minecraft:acacia_pressure_plate[powered=true] unless block 794 -58 7 minecraft:acacia_pressure_plate[powered=true] run fill 791 -58 12 791 -56 12 minecraft:magenta_concrete
