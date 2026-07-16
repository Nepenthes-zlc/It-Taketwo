# Tick logic for scene: tier_path_hard_02
execute if block 1541 -57 8 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 1540 -58 12 1541 -58 18 minecraft:cyan_concrete
execute if block 1541 -57 9 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 1540 -58 12 1541 -58 18 minecraft:cyan_concrete
execute if block 1542 -57 8 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 1540 -58 12 1541 -58 18 minecraft:cyan_concrete
execute if block 1542 -57 9 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 1540 -58 12 1541 -58 18 minecraft:cyan_concrete
execute unless block 1541 -57 8 minecraft:polished_blackstone_pressure_plate[powered=true] unless block 1541 -57 9 minecraft:polished_blackstone_pressure_plate[powered=true] unless block 1542 -57 8 minecraft:polished_blackstone_pressure_plate[powered=true] unless block 1542 -57 9 minecraft:polished_blackstone_pressure_plate[powered=true] run fill 1540 -58 12 1541 -58 18 minecraft:air
