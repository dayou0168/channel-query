#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="channel-query-bot"

systemctl status ${SERVICE_NAME} --no-pager
journalctl -u ${SERVICE_NAME} -n 80 --no-pager
