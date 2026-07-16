# Tick logic for scene: tier_elevator_hard_08
execute if block 820 -58 4 minecraft:dark_oak_pressure_plate[powered=true] run fill 822 -58 11 822 -56 11 minecraft:air
execute if block 820 -58 5 minecraft:dark_oak_pressure_plate[powered=true] run fill 822 -58 11 822 -56 11 minecraft:air
execute if block 821 -58 4 minecraft:dark_oak_pressure_plate[powered=true] run fill 822 -58 11 822 -56 11 minecraft:air
execute if block 821 -58 5 minecraft:dark_oak_pressure_plate[powered=true] run fill 822 -58 11 822 -56 11 minecraft:air
execute unless block 820 -58 4 minecraft:dark_oak_pressure_plate[powered=true] unless block 820 -58 5 minecraft:dark_oak_pressure_plate[powered=true] unless block 821 -58 4 minecraft:dark_oak_pressure_plate[powered=true] unless block 821 -58 5 minecraft:dark_oak_pressure_plate[powered=true] run fill 822 -58 11 822 -56 11 minecraft:purple_concrete
