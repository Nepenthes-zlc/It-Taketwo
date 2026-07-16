# Tick logic for scene: tier_elevator_hard_05
execute if block 729 -58 6 minecraft:birch_pressure_plate[powered=true] run fill 732 -58 12 732 -56 12 minecraft:air
execute if block 729 -58 7 minecraft:birch_pressure_plate[powered=true] run fill 732 -58 12 732 -56 12 minecraft:air
execute if block 730 -58 6 minecraft:birch_pressure_plate[powered=true] run fill 732 -58 12 732 -56 12 minecraft:air
execute if block 730 -58 7 minecraft:birch_pressure_plate[powered=true] run fill 732 -58 12 732 -56 12 minecraft:air
execute unless block 729 -58 6 minecraft:birch_pressure_plate[powered=true] unless block 729 -58 7 minecraft:birch_pressure_plate[powered=true] unless block 730 -58 6 minecraft:birch_pressure_plate[powered=true] unless block 730 -58 7 minecraft:birch_pressure_plate[powered=true] run fill 732 -58 12 732 -56 12 minecraft:cyan_concrete
