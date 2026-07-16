# Tick logic for scene: tier_elevator_hard_02
execute if block 643 -58 4 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 642 -58 11 642 -56 11 minecraft:air
execute if block 643 -58 5 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 642 -58 11 642 -56 11 minecraft:air
execute if block 644 -58 4 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 642 -58 11 642 -56 11 minecraft:air
execute if block 644 -58 5 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 642 -58 11 642 -56 11 minecraft:air
execute unless block 643 -58 4 minecraft:polished_blackstone_pressure_plate[powered=true] unless block 643 -58 5 minecraft:polished_blackstone_pressure_plate[powered=true] unless block 644 -58 4 minecraft:polished_blackstone_pressure_plate[powered=true] unless block 644 -58 5 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 642 -58 11 642 -56 11 minecraft:orange_concrete
