# Tick logic for scene: tier_path_hard_06
execute if block 1661 -57 8 minecraft:jungle_pressure_plate[powered=true] run fill 1660 -58 12 1661 -58 18 minecraft:yellow_concrete
execute if block 1661 -57 9 minecraft:jungle_pressure_plate[powered=true] run fill 1660 -58 12 1661 -58 18 minecraft:yellow_concrete
execute if block 1662 -57 8 minecraft:jungle_pressure_plate[powered=true] run fill 1660 -58 12 1661 -58 18 minecraft:yellow_concrete
execute if block 1662 -57 9 minecraft:jungle_pressure_plate[powered=true] run fill 1660 -58 12 1661 -58 18 minecraft:yellow_concrete
execute unless block 1661 -57 8 minecraft:jungle_pressure_plate[powered=true] unless block 1661 -57 9 minecraft:jungle_pressure_plate[powered=true] unless block 1662 -57 8 minecraft:jungle_pressure_plate[powered=true] unless block 1662 -57 9 minecraft:jungle_pressure_plate[powered=true] run fill 1660 -58 12 1661 -58 18 minecraft:air
