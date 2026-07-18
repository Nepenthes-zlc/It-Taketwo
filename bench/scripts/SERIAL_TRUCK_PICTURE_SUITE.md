# Serial Truck/Picture Suite

Runs five experiments serially with 16 Minecraft instances and four valid episodes per task:

1. Qwen2.5-VL-7B Picture
2. Qwen3-VL-8B Truck
3. Qwen3-VL-8B Picture
4. Qwen3.5-9B Truck
5. Qwen3.5-9B Picture
6. InternVL3.5-8B Truck
7. InternVL3.5-8B Picture

Qwen3.5 uses `/local_nvme/tmp/qwen35_vllm_clean/bin/python` with vLLM 0.24.0. The suite cleans Minecraft between experiments, reuses vLLM for adjacent experiments using the same model, and stops vLLM before switching models.

```bash
bash bench/scripts/run_serial_truck_picture_suite.sh start
bash bench/scripts/run_serial_truck_picture_suite.sh status
bash bench/scripts/run_serial_truck_picture_suite.sh stop
bash bench/scripts/run_serial_truck_picture_suite.sh resume
```

Results are written to `bench/runs/<task>/<date>/4times/`. Suite state and logs are written to `bench/runs/serial_suites/`.
