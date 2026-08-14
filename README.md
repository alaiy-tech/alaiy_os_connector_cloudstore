# Alaiy OS Connector: Cloudstore

Connects a Cloudstore supplier account to [Alaiy OS](https://alaiy.com),
syncing the supplier's category tree and item catalogue.

## Features

- **Category tree sync** — pulls Cloudstore's category hierarchy into
  Alaiy OS.
- **Item sync** — pulls the supplier's catalogue of items, kept up to date
  on demand or on a schedule.
- **Secure authentication** — Bearer token auth, with a live Test
  Connection check before enabling.
- **Sync status and logging** — every sync run is tracked, so failures are
  visible rather than silent.

## Setup

1. In Alaiy OS: open **Cloudstore Connector Settings** and fill in the
   Cloudstore API URL and Bearer Token.
2. Click **Test Connection** to confirm the credentials work.
3. Enable the connector and save.
4. Trigger a Category Tree sync, then an Items sync, from the connector's
   dashboard.

## License

AGPL-3.0
