# Tick logic for scene: tier_path_hard_08
execute if block 1721 -57 8 minecraft:dark_oak_pressure_plate[powered=true] run fill 1720 -58 12 1721 -58 18 minecraft:orange_concrete
execute if block 1721 -57 9 minecraft:dark_oak_pressure_plate[powered=true] run fill 1720 -58 12 1721 -58 18 minecraft:orange_concrete
execute if block 1722 -57 8 minecraft:dark_oak_pressure_plate[powered=true] run fill 1720 -58 12 1721 -58 18 minecraft:orange_concrete
execute if block 1722 -57 9 minecraft:dark_oak_pressure_plate[powered=true] run fill 1720 -58 12 1721 -58 18 minecraft:orange_concrete
execute unless block 1721 -57 8 minecraft:dark_oak_pressure_plate[powered=true] unless block 1721 -57 9 minecraft:dark_oak_pressure_plate[powered=true] unless block 1722 -57 8 minecraft:dark_oak_pressure_plate[powered=true] unless block 1722 -57 9 minecraft:dark_oak_pressure_plate[powered=true] run fill 1720 -58 12 1721 -58 18 minecraft:air
