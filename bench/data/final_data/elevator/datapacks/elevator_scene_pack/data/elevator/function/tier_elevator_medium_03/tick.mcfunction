# Tick logic for scene: tier_elevator_medium_03
execute if block 369 -58 7 minecraft:oak_pressure_plate[powered=true] run fill 369 -58 12 370 -56 12 minecraft:air
execute if block 369 -58 8 minecraft:oak_pressure_plate[powered=true] run fill 369 -58 12 370 -56 12 minecraft:air
execute if block 369 -58 9 minecraft:oak_pressure_plate[powered=true] run fill 369 -58 12 370 -56 12 minecraft:air
execute if block 370 -58 7 minecraft:oak_pressure_plate[powered=true] run fill 369 -58 12 370 -56 12 minecraft:air
execute if block 370 -58 8 minecraft:oak_pressure_plate[powered=true] run fill 369 -58 12 370 -56 12 minecraft:air
execute if block 370 -58 9 minecraft:oak_pressure_plate[powered=true] run fill 369 -58 12 370 -56 12 minecraft:air
execute if block 371 -58 7 minecraft:oak_pressure_plate[powered=true] run fill 369 -58 12 370 -56 12 minecraft:air
execute if block 371 -58 8 minecraft:oak_pressure_plate[powered=true] run fill 369 -58 12 370 -56 12 minecraft:air
execute if block 371 -58 9 minecraft:oak_pressure_plate[powered=true] run fill 369 -58 12 370 -56 12 minecraft:air
execute unless block 369 -58 7 minecraft:oak_pressure_plate[powered=true] unless block 369 -58 8 minecraft:oak_pressure_plate[powered=true] unless block 369 -58 9 minecraft:oak_pressure_plate[powered=true] unless block 370 -58 7 minecraft:oak_pressure_plate[powered=true] unless block 370 -58 8 minecraft:oak_pressure_plate[powered=true] unless block 370 -58 9 minecraft:oak_pressure_plate[powered=true] unless block 371 -58 7 minecraft:oak_pressure_plate[powered=true] unless block 371 -58 8 minecraft:oak_pressure_plate[powered=true] unless block 371 -58 9 minecraft:oak_pressure_plate[powered=true] run fill 369 -58 12 370 -56 12 minecraft:yellow_concrete
