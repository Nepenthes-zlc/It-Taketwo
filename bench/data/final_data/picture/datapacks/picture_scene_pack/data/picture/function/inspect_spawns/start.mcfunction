scoreboard objectives add spawn_inspect dummy
schedule clear picture:inspect_spawns/tick
tag @a remove spawn_inspector
tag @s add spawn_inspector
scoreboard players set @s spawn_inspect 0
function picture:inspect_spawns/tick
