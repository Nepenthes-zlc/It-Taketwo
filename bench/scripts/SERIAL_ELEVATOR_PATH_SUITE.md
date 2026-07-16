# Serial Elevator/Path Suite

The suite runs these experiments in order, each with 16 Minecraft instances
and four valid episodes per task:

1. Qwen2.5-VL-7B Path
2. Qwen3-VL-8B Elevator
3. Qwen3-VL-8B Path
4. Qwen3.5-9B Elevator
5. Qwen3.5-9B Path

Qwen2.5 and Qwen3 use the `verl` environment. Qwen3.5 uses
`/local_nvme/tmp/vllm024env`, because it requires the newer Qwen3.5 model
implementation in vLLM 0.24.0. Qwen3.5 thinking is disabled server-side so
the existing short JSON action protocol remains unchanged.

```bash
# Start in tmux
bash bench/scripts/run_serial_elevator_path_suite.sh start

# Show suite state and per-experiment paths
bash bench/scripts/run_serial_elevator_path_suite.sh status

# Stop benchmark, Minecraft, and vLLM cleanly
bash bench/scripts/run_serial_elevator_path_suite.sh stop

# Resume the latest stopped/failed suite
bash bench/scripts/run_serial_elevator_path_suite.sh resume
```

Suite logs and `state.json` are stored under `bench/runs/serial_suites/`.
Each experiment stores its own controller log under its normal
`bench/runs/<task>/<date>/4times/` result directory. The same model server is
reused across its Elevator and Path experiments; Minecraft is cleaned between
every experiment, and vLLM is stopped before the next model starts.
