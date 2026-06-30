# Rollback / Uninstall

The voice console is standalone. Rolling it back does not require Hermes source changes.

## Stop a foreground dev server

Press `Ctrl-C` in the terminal running `voice-console serve`.

## Remove a systemd service

If installed as a service:

```bash
sudo systemctl stop hermes-voice-console.service
sudo systemctl disable hermes-voice-console.service
sudo rm /etc/systemd/system/hermes-voice-console.service
sudo systemctl daemon-reload
```

## Remove local artifacts

```bash
rm -rf /root/DEV/hermes-voice-console/.venv
rm -rf /root/DEV/hermes-voice-console/frontend/node_modules
rm -rf /root/DEV/hermes-voice-console/frontend/dist
```

Do not remove `.env` until you have confirmed no other local process depends on the copied provider/target credentials.

## Hermes target cleanup

If you enabled API Server only for voice-console testing, revert through Hermes configuration/service management. Do not edit Hermes source. Remove or rotate target `API_SERVER_KEY` values if they were only created for this console.
