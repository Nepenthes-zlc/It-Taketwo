scoreboard objectives add spawn_inspect dummy
schedule clear path:inspect_spawns/tick
tag @a remove spawn_inspector
tag @s add spawn_inspector
scoreboard players set @s spawn_inspect 0
function path:inspect_spawns/tick
