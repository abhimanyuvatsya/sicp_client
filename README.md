# Philips SICP Tablet Control Service

This project turns the original `sicp_client` helper into a resilient service capable of managing multiple Philips signage tablets from a Raspberry Pi. It exposes LED colour and panel power controls over MQTT (with Home Assistant auto-discovery), keeps the state synchronised in both directions, and offers a local web UI for manual testing and troubleshooting.

The service targets a Raspberry Pi 3B running Raspberry Pi OS Lite, but it can run on any modern Linux system with Python 3.9+.

## Features

- **Multi-tablet management** – configure any number of tablets (tested with 5) and poll them in parallel.
- **Robust SICP transport** – retry logic with post-action verification (`GET` after `SET`/`POWER`) and state caching.
- **Two-way MQTT bridge** – publishes state updates and listens for commands with configurable topics; Home Assistant auto-discovery exposes an RGB light entity for the LED strip and a switch entity for panel power.
- **Web dashboard** – bundled FastAPI UI for issuing manual commands, viewing tablet state, and tailing recent logs.
- **Ansible automation** – end-to-end playbook for provisioning a Raspberry Pi, installing dependencies, templating configuration, and enabling a systemd service.
- **Backwards-compatible CLI** – the historic `sicp_client.py` script still exists for quick one-off diagnostics.

## Repository layout

```
.
├── sicp_service.py             # Async service entry point (invoked by systemd)
├── sicp_client/                # Python package with protocol, MQTT, web UI, ...
├── config.example.yml          # Example configuration for five tablets
├── requirements.txt            # Python dependencies for the service
└── ansible/                    # Automation playbook and role
```

## Installation (manual)

1. Create and activate a Python virtual environment (recommended on development machines):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Create a configuration file (`config.yml`). Use `config.example.yml` as a starting point and adjust:
   - The `tablets` list to match the static IP addresses (`192.168.2.x`) of your Philips devices.
   - The `mqtt` section to point at your Home Assistant Mosquitto add-on (credentials can be stored with Ansible vault later).
   - Optional per-tablet polling intervals or feature toggles (`ha_light`, `ha_power_switch`).

3. Launch the service:

   ```bash
   python sicp_service.py --config ./config.yml --log-level INFO
   ```

   The web UI listens on `http://<pi-address>:8080/` by default. The console log will display MQTT connection status and per-tablet polling updates.

4. (Optional) To stop the service press `Ctrl+C`. When running under systemd the service will automatically restart on failure.

## Web UI

Navigate to `http://<pi-address>:8080/` to:

- View each tablet’s online/LED/power state and the timestamp of the last successful poll.
- Trigger LED colour changes, toggle power, or request a manual refresh.
- Inspect recent log lines captured by the in-memory log buffer.
- Call REST endpoints programmatically:
  - `GET /api/tablets` returns the status of all tablets.
  - `GET /api/tablets/<slug>` returns a specific tablet (slug = lower-case, hyphenated name).
  - `GET /api/logs` returns the cached log messages.

## MQTT & Home Assistant

When the MQTT section is populated the bridge connects to your broker and publishes Home Assistant discovery payloads:

- **Light entity** – `homeassistant/light/<slug>_led/config` using JSON schema with RGB support.
- **Switch entity** – `homeassistant/switch/<slug>_power/config` to control panel power.

Runtime topics (retain-enabled):

| Topic | Direction | Payload |
| ----- | --------- | ------- |
| `sicp/<slug>/availability` | Service → MQTT | `online` / `offline`
| `sicp/<slug>/led/state` | Service → MQTT | `{"state": "ON|OFF", "color": {"r":0-255,"g":0-255,"b":0-255}}`
| `sicp/<slug>/led/attributes` | Service → MQTT | Diagnostic metadata (hex colour, last success/error)
| `sicp/<slug>/led/set` | MQTT → Service | Same JSON schema as the state topic
| `sicp/<slug>/power/state` | Service → MQTT | `ON` / `OFF`
| `sicp/<slug>/power/set` | MQTT → Service | `ON` / `OFF`
| `sicp/<slug>/refresh` | MQTT → Service | Any payload triggers an immediate poll

Every command sent via MQTT is acknowledged by querying the tablet again; state publications are retained so Home Assistant receives values across restarts.

## Ansible deployment

A full automation workflow is provided under `ansible/`:

1. Copy `ansible/inventory.example` to `inventory` and edit the host/IP/SSH user.
2. Create `group_vars/sicp_tablets.yml` describing the tablets and MQTT credentials (see `ansible/README.md`).
3. Run the playbook:

   ```bash
   ansible-playbook -i inventory ansible/deploy.yml
   ```

The role installs system packages, sets up a dedicated `sicp` user, creates a Python virtual environment, deploys the configuration, registers `sicp.service`, and ensures it is enabled on boot. Set `sicp_repo_url` to point at your Git repository; leave it blank to copy the local working tree.

## Backwards-compatible CLI

For one-off diagnostics the original CLI still works:

```bash
python sicp_client.py set --color '#FFC800'
python sicp_client.py power off
python sicp_client.py get
```

It relies on the same protocol module as the service and honours the `--host`, `--timeout`, and retry options.

## Troubleshooting

- Increase verbosity with `--log-level DEBUG` when launching `sicp_service.py` manually.
- The web UI’s log panel mirrors the systemd journal when running as a service.
- If MQTT credentials are wrong the bridge will retry every `reconnect_interval` seconds; check the logs for authentication errors.
- Power state reporting is best-effort because different Philips firmware revisions expose it differently. The service verifies LED commands via the `GET` frame and warns when the power acknowledgement disagrees with the requested state.

## License

MIT
