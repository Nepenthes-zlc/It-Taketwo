# It-Taketwo Benchmark Portable Bundle

This bundle contains the benchmark runner, elevator/path tasks and datapacks,
Minecraft runtime libraries/assets, and one clean source instance. Model
weights are distributed as a separate archive.

## Requirements

- Linux x86_64 with NVIDIA drivers and four visible GPUs
- Java 21 at `/usr/lib/jvm/java-21-openjdk-amd64`, or `JAVA_HOME` set
- VirtualGL (`vglrun`) with `egl0` through `egl3`
- Python 3.12 environment with the versions listed in `requirements-portable.txt`
- `tmux`, `jq`, and standard GNU utilities
- Optional: `ffmpeg` for rendering review videos

## Setup

Extract both archives into the same parent directory, then run:

```bash
cd It-Taketwo
bash bench/portable/setup_portable.sh
bash bench/portable/check_env.sh
```

The setup script creates `env/instance-train-01` through
`env/instance-train-16` from `env/instance-test-01` and writes portable Qwen
benchmark YAML files under `bench/yaml/portable/`.

## Start Elevator Evaluation

```bash
bash bench/portable/start_elevator_qwen25vl7b_4times.sh
```

The benchmark runs Easy, Medium, and Hard through one global queue. Minecraft
is prewarmed once, idle instances immediately take the next episode, abnormal
attempts are requeued, and all instances are cleaned after 400 valid episodes.

The script prints the tmux session and run directory. Use
`bench/scripts/bench.py status --run-dir <run-directory>` to inspect progress.
Results are stored under `bench/runs/elevator/<date>/4times/`.
