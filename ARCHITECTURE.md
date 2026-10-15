# Architecture — Pylontech Remote

Status: **proposal** (phase 4, 2026-10-15). No code is written against it yet.
Facts it relies on are verified in [docs/CONSOLE-NOTES.md](docs/CONSOLE-NOTES.md) and
[CHANGES-ON-CERBO.md](CHANGES-ON-CERBO.md).

## 1. Goals

1. Remote equivalent of Pylontech BatteryView on a Victron Cerbo GX: live per-module and per-cell data.
2. **Complete history and event archive** read from the battery, kept **beyond** what the battery
   stores (~1800 history records ≈ 37 days, ~85+ events), with the raw console replies preserved
   verbatim as the source of truth.
3. **Export** in the format Pylontech support asks for: the BatteryView event/history files
   (`info` + `stat` + `datalist` table, no per-cell detail) — format known from a sample (§4.11).
4. Robust and reproducible: survives Venus OS updates and reboots, installs on any Venus OS device,
   not tied to one installation; other battery types can be added later.

Non-goals: changing any battery setting; anything on the Victron side (ESS, DVCC, BMS selection,
settings); replacing the BMS-CAN link.

## 2. Hard constraints

| Constraint | Consequence in the design |
|---|---|
| Battery gets **read-only** commands only | One allow-list, enforced in the lowest layer that writes to the port (§4.2). No raw console pass-through anywhere — not in MQTT, not in the UI. |
| BMS-CAN must not be affected | The service never touches CAN, D-Bus battery services or Victron settings. It must **not** publish a `com.victronenergy.battery.*` D-Bus service (the system could pick it as the battery monitor). |
| The console port has exactly one owner | One long-running service owns each port; everything else asks the service (§4.4). Port opened with `exclusive=True`, checked with `fuser` before opening. |
| Console timing | 1.2–2 s between commands; one `data` record 0.4 s (master) / 0.6 s (slave); full `datalist history 0` ~104 s; paging answered with Enter (any other key aborts). |
| Flash wear | Batched SQLite writes; live data not written to flash on every poll (§4.6). |
| Venus OS updates replace `/` (incl. `/etc`) | Everything lives in `/data/pylontech/`; `/data/rc.local` re-creates the udev rule and the service link at every boot (§4.9). |
| Resources | Python 3.12 stdlib + pyserial 3.5 + paho-mqtt 2.0 — all already on Venus OS Large. **No package installs.** (`tomllib` is missing on Venus → config in INI via `configparser`.) |

## 3. Overview

```
                  ┌──────────────────────── pylontechd (one process, /data/pylontech) ───────────────────────┐
 battery console  │                                                                                            │
 (RS232 → USB) ───┤ Transport ─► ConsoleSession ─► Adapter (Pylontech console) ─► Job runner (priority queue)  │
 one per port     │ (port, lock)  (allow-list,     (commands + pure parsers)       live │ sync │ export │ maint. │
                  │               prompt, paging,                                    │      │                  │
                  │               raw transcript)                                    ▼      ▼                  │
                  │                                                  MQTT publisher   Archive (SQLite + raw)    │
                  └──────────────────────────────────────────────────────┬──────────────────┬─────────────────┘
                                                                         │                  │
                                            local FlashMQ (localhost:1883)                  │ files
                                                   │            ▲                           ▼
                                                   ▼            │ commands      /data/pylontech/exports
                                        Node-RED Dashboard 2.0 (UI only; via LAN or VRM proxy)
```

## 4. Components

### 4.1 Transport (per port)

- Opens the serial port with DTR/RTS low **before** `open()` (no pulse), 115200 8N1, no flow
  control, `exclusive=True` (TIOCEXCL). Refuses to open if `fuser` reports another holder.
- Holds an advisory lock `/run/pylontech/<tty>.lock` so CLI tools (and a temporary manual session
  in maintenance mode) can see that the service owns the port.
- Detects a vanished device (cable unplugged, USB reset) → closes, waits, reopens with back-off.
- Identifies the cable by udev properties (FTDI serial, or USB path for adapters without a serial
  such as the current CH340 test cable).

### 4.2 ConsoleSession

The only code that writes to the port. Responsibilities:

- **Allow-list**: every command is matched (full match) against a fixed list derived from
  CONSOLE-NOTES: `bat N`, `info [N]`, `stat [N]`, `pwr`, `config` (no args),
  `data [module] history|event N`, `datalist history|event N`, `log`, `help [cmd]`. Anything else raises before a single byte is sent.
  Unit tests assert that the forbidden commands from CONSOLE-NOTES are rejected.
- Wake/resync: send `\n`, wait for the `xxx>` prompt at the end of the buffer; on a stray paging
  prompt send Enter until the prompt returns.
- Paging: answer `Press [Enter] …` with `\r` only (never space — that aborts the output).
- End of reply = prompt at the end of the buffer; fallback idle timeout; hard timeout per command.
- Enforced gap between commands (default 1.2 s, configurable; shorter gap for master-local
  `data` reads only after testing).
- Returns a `RawReply` (command, sent/finished UTC, bytes verbatim, end reason, page count) — the
  unit stored in the archive.

### 4.3 Adapters

Interface (`adapters/base.py`), independent of transport details:

```
discover()               -> StackInfo (modules: index, model, barcode, firmware)
read_live()              -> LiveSnapshot (pack + per module + per cell, thresholds)
history_bounds(module, kind) -> (first_index, last_index)        # kind: history | event
read_record(module, kind, index) -> (RawReply, ParsedRecord)
read_log()               -> (RawReply, [LogEntry])
```

- `PylontechConsoleAdapter` implements it for US-series firmware B69.x (verified on B69.25.0.0).
- **Parsers are pure functions** (`text -> dataclass`) with a `parser_version`; they parse by
  labels and column headers, not by column position, and keep unknown fields instead of dropping
  them. They are tested against captured replies (sanitised fixtures in `tests/fixtures/`).
- Later adapters (other battery brands, Pylontech's binary RS485 protocol, a different firmware)
  plug in without touching the job runner, archive or UI.

**Slave modules.** Everything goes through the master's console: live data (`bat N`, `info N`,
`stat N`) and history/events (`data N history|event i` — verified on all 4 modules; a missing
module answers `Target device is not present`). One cable on the master is enough. The design
still allows **several ports** (other stacks, or a direct cable per module if a firmware ever
lacks the relay), each with its own adapter instance and job worker. The `log` command has no
module argument and stays master-only.

### 4.4 Job runner

One worker thread per port; jobs in a priority queue; every job is **chunked** (a few commands,
then it yields) so a long sync never starves live data.

| Job | Trigger | Work | Priority |
|---|---|---|---|
| `live` | on demand (dashboard Live switch, auto-off after 30 min): one cycle every 8 s | `pwr` + `bat 1..n`, one snapshot per cycle (all values change at once); `config`/`info`/`stat` on start, `stat` every 10 min | high |
| `sync_events` | every 30 min + on start | incremental per module, see §4.5 | normal |
| `sync_history` | every 30 min + on start | incremental per module, chunks of ~20 records | normal |
| `sync_log` | optional (off by default) | `log` (32 entries, newest first) | low |
| `export` | on request | reads **only the archive**, never the port | — (no port) |
| `maintenance` | on request | stops all port jobs and closes the port (§4.8) | top |

First full sync (this stack): master tables via `datalist` in ~2 min; per-record `data` reads
(cell detail for the master, everything for the 3 slaves) ~1800 + ~100 records per module at
0.4–0.6 s plus the pause → **~3–4 h**, interleaved with live polling. After that: 1 history record
per module per 30 min (each module has its own 30-min phase).

### 4.5 Incremental sync

Battery indexes are positions, not identities (index 0 = oldest; the history ring buffer drops the
oldest records in blocks of 8, so indexes jump). Identity of a record is therefore
`(module barcode, kind, battery timestamp, sha256 of the normalised reply body)`.

0. Master, cheap path: `datalist history|event <last+1>` returns all new rows in one reply
   (no cell detail); per-cell detail comes from `data` records.
1. Find the last index: `stat [N]` gives the record counts (`Data Items` = events,
   `HisData Items` = history); last index = count − 1 (verified). A probe past the end returns
   `Invalid command` and guards against a record written in between.
2. Read **from newest backwards** until a record already in the archive is met → stop.
   Works whether the buffer shifts, stays fixed, or was cleared by someone else.
3. If the oldest record still on the battery is newer than the newest one in the archive, the
   archive has a **gap** (data lost while the service was off) → recorded and shown in the UI.
4. Each chunk is committed in one transaction.

### 4.6 Archive (SQLite, `/data/pylontech/archive.db`)

- `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`; one transaction per chunk (≈ 20 records or
  10 min), so flash writes are few and large.
- **Raw is the source of truth**: every record reply is stored verbatim (zlib-compressed) with
  capture metadata; parsed tables can be rebuilt from raw at any time (`reparse` command when a
  parser improves).
- Tables (sketch):
  - `module(barcode PK, model, firmware, first_seen, last_seen, stack_position)`
  - `raw_reply(id, port, module_barcode, kind, battery_index, command, sent_utc, duration_s,
    end_reason, body_zlib, sha256, UNIQUE(module_barcode, kind, battery_ts, sha256))`
  - `record(raw_id, kind, battery_ts_text, battery_ts_local, cerbo_utc_est, voltage_mv, current_ma,
    temperature_mc, soc_pct, coulomb_mah, base_state, volt_state, curr_state, temp_state,
    coul_status, power_events, bat_events, system_fault, parser_version)`
  - `record_cell(raw_id, cell, voltage_mv, current_ma, temperature_mc, base_state, volt_state,
    curr_state, temp_state, soc_pct)`
  - `sync_state(module_barcode, kind, last_count, newest_battery_ts, newest_sha256, updated_utc)`
  - `clock_offset(module_barcode, measured_utc, offset_s, method)` — the battery clock is not set
    (forbidden) and runs ~9 min ahead; the offset is estimated at each sync from the newest `log`
    entry/record and kept so times can be corrected later. Battery time is always stored verbatim.
- Live data: **not** written per poll. Optional downsampled snapshot (e.g. every 15 min, min/max
  cell per module) — decided later.
- Size: ~2.4 KB per raw record, compresses ~5–10×; ≈ 48 history records/day per module → a few MB
  per module per year (4 modules: well under 100 MB/year). `/data` has 4.1 GB free.

### 4.7 Publishing and control (MQTT)

- Local FlashMQ broker (`localhost:1883`, already running; "MQTT on LAN" is enabled on this
  Cerbo). Own namespace **`pylontech/<stack-id>/…`**. The VRM bridge forwards only `N/`, `P/`,
  `I/` topics, so nothing leaves the house. Never publish under `N/`, `R/`, `W/`.
- Retained state topics: `…/status` (service health, last success, errors, mode), `…/live`
  (pack + modules + cells JSON), `…/archive` (counts, newest record, gaps, sync progress).
- Commands: `…/cmd/<action>` with an enumerated set only — `sync_now`, `export`,
  `maintenance_on`, `maintenance_off`. Reply on `…/cmd/<action>/result`. No command can carry a
  console command. (Anyone on the LAN can reach the broker; that is acceptable only because the
  command set is harmless.)
- D-Bus: not in v1. If ever, only a non-battery service type, never `com.victronenergy.battery`.

### 4.8 Maintenance mode

Stops all jobs for a port, closes it and drops the lock, so the original reader, a manual console
session or BatteryView can use it. Auto-returns to normal after a timeout (default 2 h) or on
`maintenance_off`.

Optional, decision needed: a **network bridge** of the port during maintenance (RFC 2217 —
pyserial ships the server code) so BatteryView on a PC can talk to the battery remotely through a
virtual COM port. Off by default, LAN only, time-limited. Note: BatteryView can send *any*
command, so the read-only guarantee does not hold while the bridge is open.

### 4.9 Installation, boot and survival of Venus OS updates

```
/data/pylontech/
  app/                      code (pylontechd, adapters, tools)
  config.ini                ports, cable identification, intervals, MQTT prefix
  udev/zz-pylontech.rules   generated by install.sh from config.ini
  service/run, log/run      daemontools service (svscan picks it up via /service link)
  archive.db                archive
  exports/                  generated exports
/data/rc.local              (created or appended, idempotent) → /data/pylontech/boot.sh
/data/log/pylontech/        multilog, small (s25000 n4)
```

- `install.sh` (rewritten): detects the cable (FTDI by serial, CH340/others by USB path),
  writes `config.ini` and the udev rule, shows the user exactly what it will change, writes
  nothing outside `/data` except through `boot.sh`. No `opkg`, no `pip`, no restart of
  serial-starter, no `udevadm trigger` on all devices.
- `boot.sh` (from `/data/rc.local`, runs late at boot): copy the rule to
  `/etc/udev/rules.d/` if missing, reload udev, re-trigger **only** the matching tty with
  `--action=add` (serial-starter then drops the port by itself — verified), then link
  `/service/pylontech → /data/pylontech/service`. Idempotent; on any error it logs and does
  nothing else.
- Rule file name `zz-…` so it is processed **after** Venus OS's `serial-starter.rules` (a `99-…`
  name is overridden — verified).
- `uninstall.sh` reverses everything; each change is also listed in CHANGES-ON-CERBO.md.

### 4.10 UI (Node-RED, Dashboard 2.0)

- Node-RED becomes UI only: subscribes to `pylontech/#`, shows live data, archive status, gaps,
  sync progress; buttons publish the enumerated commands. **No `exec` node**, no direct port access.
- Export download: a Node-RED HTTP endpoint serving files from `/data/pylontech/exports/` (read only).
- Reachable on the LAN and through the VRM Node-RED proxy (to be verified for Dashboard 2.0).
- The original widget's look is reused; the existing user flows (ESS automation) are not touched.

### 4.11 Exporters

```
Exporter.export(module_barcode, kind, time_range) -> list[path]
```

- `batteryview` — files named and structured exactly like BatteryView's
  (`<barcode>_<event|history>_<YYYYMMDDhhmmss>.txt` = verbatim `info` + `stat` + `datalist … 0`
  transcript, see CONSOLE-NOTES). **Master:** produced verbatim from a fresh/archived
  `datalist` capture, extended with archived records older than the battery still holds.
  **Slaves:** `datalist` cannot be relayed, so the table is rebuilt from `data <module> …` records
  (`info N`/`stat N` stay verbatim). All columns support uses are derivable exactly (verified on the
  master); only `Rec_chg/dsg_cur`, `Sys_Rec…` and `ID Cur` (stack-level, master only) stay `-`.
  Marked as reconstructed. Whether support accepts that, or wants the cable on each module once, is open.
- `raw` — the stored replies concatenated verbatim.
- `csv` — parsed records and cells (per-cell detail only exists in `data` records).

### 4.12 Capability check and guided cable move (fallback)

At start (and after a firmware change seen in `info N`) the adapter probes, read-only, what the
stack supports: firmware per module, `datalist` columns, and whether `data <module> …` is relayed
to slaves. The result is stored and shown in the UI.

If slaves cannot be read through the master (or support wants a verbatim slave file), the
**technician** runs a **guided cable move** remotely (dashboard via LAN/VRM) while the **customer**
moves the cable following instructions **over the phone** — customers usually have no access to the
dashboard (admin rights), so the customer needs nothing but the phone.

1. Technician starts the wizard; the dashboard shows which module the cable is on right now
   (live `info`: barcode, device address, stack position) and the next target module with its
   barcode, so the customer can be asked to read the label on the module.
2. The service notices the change (`info` → different barcode / device address), shows it to the
   technician, and captures `info`, `stat`, `datalist event 0`, `datalist history 0` verbatim
   (~2 min) — exactly the BatteryView file for that module.
3. Next module … finally "cable back into the master"; the service confirms the master is back and
   resumes normal operation.

The USB end stays in the Cerbo, so the udev identity of the cable does not change. Nothing but the
allow-listed read commands is sent at any step; a wrong or missing module only produces a message.

**Risk: the wrong socket.** The module front has several identical RJ45 sockets (Console, Link
in/out between modules, CAN/RS485 to the inverter/Cerbo). Unplugging a Link or the BMS-CAN cable
disturbs the whole system. The procedure for the call therefore says, in this order: touch only the
cable that ends in the Cerbo's USB port; only the socket labelled **Console**; never unplug any
other cable. The dashboard shows a reference photo of the module front with the Console socket
marked (to be supplied). During the wizard the dashboard also shows, read-only, what the Cerbo
gets over BMS-CAN (battery alarms, `NrOfModulesOnline`, from the local MQTT `N/…` topics) and warns
the technician at once if it changes — a sign that a wrong cable was pulled.

## 5. Repository layout (target)

```
pylontech_remote/
  transport.py  session.py  allowlist.py  jobs.py  archive.py  mqtt.py  config.py
  adapters/base.py  adapters/pylontech_console.py  parsers/pylontech.py
  exporters/raw.py  exporters/csv.py  exporters/batteryview.py
pylontechd.py  pylontechctl.py
install.sh  uninstall.sh  boot.sh  udev/  service/
nodered/pylontech_remote_flow.json
tests/  tests/fixtures/ (sanitised captures)  tools/console_capture.py
legacy/ (original reader + flow, kept with attribution)
```

Tests run on a PC without a battery: parsers against fixtures, and a fake console that replays
captures through the full stack (session → adapter → jobs → archive → MQTT).

## 6. Migration

1. Original reader and flow stay as they are until the service runs.
2. Service runs in parallel with the old flow's button **disabled** (single port owner).
3. New flow replaces the old one; the old reader moves to `legacy/` with the original
   attribution (MIT, tejno). README keeps the original credit.

## 7. Open questions / decisions

| # | Question | Blocks |
|---|---|---|
| 1 | ~~Slave history via the master?~~ **Solved**: `data <module> history|event <i>` | — |
| 2 | ~~Ring buffer?~~ **Yes**: ~1796 records, oldest dropped in blocks of 8 → indexes jump; identity by time + content (as designed) | — |
| 3 | ~~BatteryView export sample~~ received. Open: does support accept a *reconstructed* table for slave modules (no remote `datalist`)? | slave export |
| 4 | Live poll interval (120 s default) and whether to keep downsampled live snapshots | archive size |
| 5 | Maintenance-mode network bridge for remote BatteryView: yes/no | §4.8 |
| 6 | FTDI cable: when, and replace the temporary CH340 rule | install |
| 7 | `log` polling: worth archiving (32 entries ≈ minutes)? | low |
| 8 | Other firmwares: collect samples with a read-only check script (§4.12) to see where `data <module> …` relaying works | compatibility |
