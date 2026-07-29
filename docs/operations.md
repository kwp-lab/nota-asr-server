# Operations

## Endpoints

- `/health` proves the HTTP process is alive.
- `/ready` proves the preloaded model is ready.
- `/v1/models` lists enabled aliases and readiness.
- `/docs` exposes Swagger UI.

## systemd

The reference unit is `deploy/systemd/nota-asr-server.service`.

Install it as a user service:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/nota-asr-server.service ~/.config/systemd/user/
cp .env.example ~/.config/nota-asr-server.env
chmod 600 ~/.config/nota-asr-server.env
systemctl --user daemon-reload
systemctl --user enable --now nota-asr-server
```

The checked-in defaults bind `0.0.0.0:8010`, so authorized machines on the
LAN can use `http://<server-lan-ip>:8010`. Binding all interfaces is not an
authorization boundary. Configure `NOTA_API_KEYS` and firewall rules before
using a shared or untrusted network.

```bash
systemctl --user status nota-asr-server
journalctl --user -u nota-asr-server -f
systemctl --user restart nota-asr-server
```

Model startup can take tens of seconds after a cold download. Readiness must
remain false until preload completes.

User services normally start when that user logs in. A host administrator may
enable lingering with `loginctl enable-linger <user>` when the service must
start at boot before an interactive login.

## Capacity

CPU inference defaults to one concurrent request. Queueing occurs inside one
process. Scale only after measuring representative long meetings; multiple
workers duplicate model memory and do not share the in-process semaphore.

The service streams uploads to disk, but the reverse proxy must also enforce a
request body limit and timeout. Monitor free disk space in the configured temp
filesystem.
