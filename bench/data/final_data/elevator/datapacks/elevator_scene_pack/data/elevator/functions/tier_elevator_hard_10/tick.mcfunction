# Tick logic for scene: tier_elevator_hard_10
execute if block 879 -58 4 minecraft:cherry_pressure_plate[powered=true] run fill 881 -58 11 881 -56 11 minecraft:air
execute if block 879 -58 5 minecraft:cherry_pressure_plate[powered=true] run fill 881 -58 11 881 -56 11 minecraft:air
execute if block 880 -58 4 minecraft:cherry_pressure_plate[powered=true] run fill 881 -58 11 881 -56 11 minecraft:air
execute if block 880 -58 5 minecraft:cherry_pressure_plate[powered=true] run fill 881 -58 11 881 -56 11 minecraft:air
execute unless block 879 -58 4 minecraft:cherry_pressure_plate[powered=true] unless block 879 -58 5 minecraft:cherry_pressure_plate[powered=true] unless block 880 -58 4 minecraft:cherry_pressure_plate[powered=true] unless block 880 -58 5 minecraft:cherry_pressure_plate[powered=true] run fill 881 -58 11 881 -56 11 minecraft:pink_concrete
