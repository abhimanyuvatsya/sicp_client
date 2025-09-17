````markdown
# SICP LED Client

Python helper for sending Philips SICP frames to the LED accent strips on a signage device.

## Requirements
- Python 3.9 or newer (ships with macOS / Linux distros)

## Usage
```bash
python3 -B sicp_client.py set --color '#FFC800'               # turn strips on with warm yellow
python3 -B sicp_client.py set --off                           # turn strips off
python3 -B sicp_client.py get                                 # request current RGB status
python3 -B sicp_client.py power on                            # power on the panel
python3 -B sicp_client.py power off                           # power off the panel
python3 -B sicp_client.py raw 09 01 00 F3 01 FF F2 00 F7 --reply  # send a custom frame
```

Flags:
- `--host` defaults to `192.168.2.98`
- `--port` defaults to `5000`
- `--timeout` controls socket timeout in seconds (default `5.0`). Increase this if the
  display responds slowly, e.g. `--timeout 10`.
- `--retries` sets how many extra attempts to make after the first send (default `2`).
- `--retry-delay` waits this many seconds between retries (default `1.0`).
- `--color` accepts hex `RRGGBB` strings with or without a leading `#`.

The script prints the exact SICP frame it sends (and any acknowledgement/reply). If you
see `Unable to reach ...`, double-check network routing/firewalls and that the display is
listening on port `5000`. Debug lines prefixed with `[debug]` describe the TCP exchange so
you can see connection and reply details.

Raw mode accepts bytes in hex (`FF`, `0xFF`) or decimal (`255`). Use `--reply` when you
expect a response frame.

````