# Airports config

Edit `airports.yaml` to control what the scanner scans.

- `origins`: airports you might fly **from**.
- `destinations`: airports you'd consider going **to**.
- An airport can appear in both lists.
- `defaults`: used by `/nomad quick`.

Each `(origin, destination, month)` in your query window costs **one
calendar call** per scan. Keep the matrix modest to stay polite to Google.
