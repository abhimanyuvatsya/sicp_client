# SICP Tablet Controller

This project manages Philips signage tablets over the SICP protocol. It offers:

- A resilient controller for LED accent lighting and power state with retry and
  confirmation checks.
- Bidirectional MQTT integration for Home Assistant (autodiscovery enabled).
- A FastAPI-powered web UI for manual control, log review, and status
  dashboards.
- An Ansible playbook for deploying the service to a Raspberry Pi (tested on Pi
  3B running Raspberry Pi OS Lite).
- A backwards-compatible command-line utility (`sicp_client.py`) for direct
  frame testing.

## Features

- Two-way synchronization: the manager polls each configured tablet and pushes
  updates to MQTT/Home Assistant while also accepting commands via MQTT.
- Per-tablet retry policies and confirmation checks after every state change.
- Structured logging with an in-memory buffer exposed through the web UI.
- Web UI served locally on the Pi for manual overrides and debugging.
- Support for managing multiple tablets from a single controller instance.

## Running locally

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `config.example.yml` to `config.yml` and adjust MQTT credentials and
tablet IP addresses. Then launch the service:

```bash
python main.py --config config.yml
```

By default the web UI listens on port `8080` (configurable via `config.yml`).

## Home Assistant integration

The controller publishes Home Assistant discovery topics for both a light (LED
accent strip) and a switch (panel power) per tablet. MQTT topics follow the
pattern `sicp/<tablet_id>/...` and use JSON payloads for the light to support RGB
color selection.

## Ansible deployment

An Ansible playbook is included under the `ansible/` directory. Update
`ansible/group_vars/all.yml` with your repository URL, MQTT credentials, and
tablet list, then run:

```bash
ansible-playbook -i ansible/inventory.ini ansible/playbook.yml
```

The playbook installs the application under `/opt/sicp`, writes the configuration
file to `/etc/sicp/config.yml`, and creates a `sicp.service` systemd unit.

## Command-line utility

The original CLI is still available for quick testing:

```bash
python3 -B sicp_client.py set --color '#FFC800'
python3 -B sicp_client.py get
python3 -B sicp_client.py power on
python3 -B sicp_client.py power status
```

## Configuration reference

See `config.example.yml` for all available options. Add or remove tablets by
editing the configuration file (or updating the Ansible variables and rerunning
the playbook).

## Logging

Logs are written to stdout, optionally a file (configured via `config.yml`), and
are kept in an in-memory ring buffer for the web UI. Use the `/logs` page to
inspect recent events, including retry attempts or protocol errors.
