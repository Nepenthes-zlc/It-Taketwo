# Tick logic for scene: tier_path_hard_05
execute if block 1631 -57 8 minecraft:birch_pressure_plate[powered=true] run fill 1630 -58 12 1631 -58 18 minecraft:red_concrete
execute if block 1631 -57 9 minecraft:birch_pressure_plate[powered=true] run fill 1630 -58 12 1631 -58 18 minecraft:red_concrete
execute if block 1632 -57 8 minecraft:birch_pressure_plate[powered=true] run fill 1630 -58 12 1631 -58 18 minecraft:red_concrete
execute if block 1632 -57 9 minecraft:birch_pressure_plate[powered=true] run fill 1630 -58 12 1631 -58 18 minecraft:red_concrete
execute unless block 1631 -57 8 minecraft:birch_pressure_plate[powered=true] unless block 1631 -57 9 minecraft:birch_pressure_plate[powered=true] unless block 1632 -57 8 minecraft:birch_pressure_plate[powered=true] unless block 1632 -57 9 minecraft:birch_pressure_plate[powered=true] run fill 1630 -58 12 1631 -58 18 minecraft:air
