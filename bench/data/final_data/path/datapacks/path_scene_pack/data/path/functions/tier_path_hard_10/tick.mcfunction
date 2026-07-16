# Tick logic for scene: tier_path_hard_10
execute if block 1781 -57 8 minecraft:cherry_pressure_plate[powered=true] run fill 1780 -58 12 1781 -58 18 minecraft:blue_concrete
execute if block 1781 -57 9 minecraft:cherry_pressure_plate[powered=true] run fill 1780 -58 12 1781 -58 18 minecraft:blue_concrete
execute if block 1782 -57 8 minecraft:cherry_pressure_plate[powered=true] run fill 1780 -58 12 1781 -58 18 minecraft:blue_concrete
execute if block 1782 -57 9 minecraft:cherry_pressure_plate[powered=true] run fill 1780 -58 12 1781 -58 18 minecraft:blue_concrete
execute unless block 1781 -57 8 minecraft:cherry_pressure_plate[powered=true] unless block 1781 -57 9 minecraft:cherry_pressure_plate[powered=true] unless block 1782 -57 8 minecraft:cherry_pressure_plate[powered=true] unless block 1782 -57 9 minecraft:cherry_pressure_plate[powered=true] run fill 1780 -58 12 1781 -58 18 minecraft:air
