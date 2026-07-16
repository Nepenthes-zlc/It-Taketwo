# Tick logic for scene: tier_elevator_medium_04
execute if block 401 -58 5 minecraft:spruce_pressure_plate[powered=true] run fill 400 -58 11 401 -56 11 minecraft:air
execute if block 401 -58 6 minecraft:spruce_pressure_plate[powered=true] run fill 400 -58 11 401 -56 11 minecraft:air
execute if block 401 -58 7 minecraft:spruce_pressure_plate[powered=true] run fill 400 -58 11 401 -56 11 minecraft:air
execute if block 402 -58 5 minecraft:spruce_pressure_plate[powered=true] run fill 400 -58 11 401 -56 11 minecraft:air
execute if block 402 -58 6 minecraft:spruce_pressure_plate[powered=true] run fill 400 -58 11 401 -56 11 minecraft:air
execute if block 402 -58 7 minecraft:spruce_pressure_plate[powered=true] run fill 400 -58 11 401 -56 11 minecraft:air
execute if block 403 -58 5 minecraft:spruce_pressure_plate[powered=true] run fill 400 -58 11 401 -56 11 minecraft:air
execute if block 403 -58 6 minecraft:spruce_pressure_plate[powered=true] run fill 400 -58 11 401 -56 11 minecraft:air
execute if block 403 -58 7 minecraft:spruce_pressure_plate[powered=true] run fill 400 -58 11 401 -56 11 minecraft:air
execute unless block 401 -58 5 minecraft:spruce_pressure_plate[powered=true] unless block 401 -58 6 minecraft:spruce_pressure_plate[powered=true] unless block 401 -58 7 minecraft:spruce_pressure_plate[powered=true] unless block 402 -58 5 minecraft:spruce_pressure_plate[powered=true] unless block 402 -58 6 minecraft:spruce_pressure_plate[powered=true] unless block 402 -58 7 minecraft:spruce_pressure_plate[powered=true] unless block 403 -58 5 minecraft:spruce_pressure_plate[powered=true] unless block 403 -58 6 minecraft:spruce_pressure_plate[powered=true] unless block 403 -58 7 minecraft:spruce_pressure_plate[powered=true] run fill 400 -58 11 401 -56 11 minecraft:lime_concrete
