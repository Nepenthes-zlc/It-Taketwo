# Tick logic for scene: elevator_crimson_black
execute if block 95 -58 5 minecraft:crimson_pressure_plate[powered=true] run fill 94 -58 8 95 -54 8 minecraft:air
execute unless block 95 -58 5 minecraft:crimson_pressure_plate[powered=true] run fill 94 -58 8 95 -54 8 minecraft:gilded_blackstone
