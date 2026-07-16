# Tick logic for scene: tier_elevator_hard_06
execute if block 761 -58 4 minecraft:jungle_pressure_plate[powered=true] run fill 760 -58 11 760 -56 11 minecraft:air
execute if block 761 -58 5 minecraft:jungle_pressure_plate[powered=true] run fill 760 -58 11 760 -56 11 minecraft:air
execute if block 762 -58 4 minecraft:jungle_pressure_plate[powered=true] run fill 760 -58 11 760 -56 11 minecraft:air
execute if block 762 -58 5 minecraft:jungle_pressure_plate[powered=true] run fill 760 -58 11 760 -56 11 minecraft:air
execute unless block 761 -58 4 minecraft:jungle_pressure_plate[powered=true] unless block 761 -58 5 minecraft:jungle_pressure_plate[powered=true] unless block 762 -58 4 minecraft:jungle_pressure_plate[powered=true] unless block 762 -58 5 minecraft:jungle_pressure_plate[powered=true] run fill 760 -58 11 760 -56 11 minecraft:blue_concrete
