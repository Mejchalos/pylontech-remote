# Changes on the Cerbo GX

Every change made on the Cerbo (root@192.168.1.150) for this project: what, where, and how to undo it.
Files under `/data/pylontech*` belong to the project; everything else is listed here.

| # | Date | What | Where | Undo |
|---|------|------|-------|------|
| 1 | 2026-10-15 | **Temporary** udev rule: serial-starter ignores the CH340 console cable (1a86:7523) in this one USB slot. New file, nothing was overwritten. Remove when the cable is replaced by an FTDI one. | `/etc/udev/rules.d/zz-pylontech-console.rules` | `rm /etc/udev/rules.d/zz-pylontech-console.rules && udevadm control --reload-rules && udevadm trigger --action=add --subsystem-match=tty --sysname-match=ttyUSB0` (serial-starter resumes probing the port) |
| 2 | 2026-10-15 | Original reader copied unchanged from the repo (commit 9f28c9a). | `/data/pylontech_reader.py` | `rm /data/pylontech_reader.py` |
| 3 | 2026-10-15 | Dashboard 2.0 `@flowfuse/node-red-dashboard` 1.33.0 installed via the Node-RED palette manager (done by the user). Runs next to the existing Dashboard 1 (`/ui`); Dashboard 2.0 is at `/dashboard`. ~200 MB in `/data`. | `/data/home/nodered/.node-red/node_modules/@flowfuse/`, `package.json` | Node-RED → Manage palette → Installed → `@flowfuse/node-red-dashboard` → Remove (only after deleting the Battery tab) |
| 4 | 2026-10-15 | `nodered/pylontech_flow.json` imported and deployed as tab **Battery** (done by the user). Dashboard: `http://<cerbo-ip>:1880/dashboard/battery`. | `/data/home/nodered/.node-red/flows.json` | Node-RED editor → delete the Battery tab and its `ui-base`/`ui-page`/`ui-group`/`ui-theme` config nodes → Deploy |

## Notes

### 1 — udev rule
Content:

```
ACTION=="add", SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="1a86", ENV{ID_MODEL_ID}=="7523", ENV{ID_PATH}=="platform-1c14400.usb-usb-0:1:1.0", ENV{VE_SERVICE}="ignore"
```

- Why `zz-` and not `99-`: udev processes rule files sorted by name across all directories. Venus OS's
  `serial-starter.rules` sets `VE_SERVICE=cgwacs:default` for every CH340 (it assumes a Zigbee
  energy-meter converter). A `99-` file runs *before* it and gets overwritten; `zz-` runs after.
- Matches on the physical USB slot (`ID_PATH`) because the CH340 has no serial number. Moving the cable
  to another USB socket makes the rule stop matching.
- `/etc` is replaced by a Venus OS update, so this rule disappears after an update (intended for a
  temporary test). The permanent solution (rule restored at boot from `/data`) is part of the rebuild.
