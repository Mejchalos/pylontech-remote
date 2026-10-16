# Pylontech console — research notes

Verified on 2026-10-15 against a 4× US3000C stack, firmware B69.25.0.0, through the RS232 console
of the master module (115200 8N1, DTR/RTS low). Raw captures stay local in `captures/` (gitignored,
they contain module serial numbers). Capture tool: `tools/console_capture.py`.

## Session basics

- Prompt: `pylon_debug>`. Every reply ends with `Command completed successfully` (or
  `Invalid command or fail to excute.` + usage), then `$$`, then the prompt.
- The console echoes the command, then `@`. Line endings are mixed (`\r`, `\n\r`, `\r\r\n`).
- Long output pauses with `Press [Enter] to be continued,other key to exit`. **Enter continues; any
  other key aborts.** The original reader answers with a space, i.e. it aborts long output.
- A paging prompt left unanswered does not block the next session (it was gone ~30 s later).
- Answer time: short commands ~0.2 s, one history/event record ~0.4 s (master's own data).

## `help`

5 pages, ~6 KB. Full text is in the local capture. Besides the read commands it lists many
commands that write, erase or control hardware (`datac`, `logc`, `statc`, `save`, `time`,
`setsoc`, `totalcoul`, `currcal`, `eepw/eepe/flaw/flae/mm`, `urates`, `shut`, `trst`, `updata`,
`login`, `prot`, `ctrl`, `config <param> <val>`, all `t…` test commands). **Never send these.**
`tools/console_capture.py` has an allow-list and refuses anything else.

Read commands relevant for history:

| Command | Help text |
|---|---|
| `data [event/history/pov/puv/plv/bov/buv/inputov/coc/coca/doc/doca/sc/use][item]` | History data load |
| `datalist [event/history/…][item/bat][batnun][volt/curr/temp/coul][item]` | Show recorded data — **`datalist <event\|history> <start>`** lists all records from `<start>` as a table; see below |
| `log` | Log information show — see below |

`data` is also listed under "Remote command" (as are `info`, `stat`, `config`, `soh`).

## Reading slave modules through the master — **works**

The module number goes **right after `data`**: `data <module> <event|history> <item>`
(verified 2026-10-15 on all 4 modules).

| Command | Result |
|---|---|
| `data 1 event 1` | identical to `data event 1` (module 1 = master) — 0.4 s |
| `data 2 event 1` / `data 3 event 1` / `data 4 event 1` | each module's own oldest event (2025-09-20 DOCA / 2024-10-02 SYSERR / 2025-03-03 BHV) — 0.6 s (relayed over the internal RS485) |
| `data 2 history 1` | module 2's own history (2026-09-08 07:24:54 — its own 30-min phase) — 0.6 s |
| `data 5 event 1` | `Target device is not present` (only 4 modules) |
| `data event 1 2`, `data history 1 2` | usage text — the module number does **not** go at the end |

The help text omits this argument, just as it omits the module number of `stat N` / `info N`.

## `data history N` / `data event N`

- **Index 0 = oldest, highest index = newest** (`data history 0` / `data event 0` exist; the
  first probes started at 1). An index past the end returns `Invalid command or fail to excute.`
  `data` and `datalist` use the **same** indexes.
- History: one record every **30 min**, a **ring buffer of ~1796 records (~37 days)**. When it is
  full the oldest records are dropped **in blocks of 8** (observed 2026-10-15: index 1 was
  26-09-08 06:59:33 at 17:24, index 0 was 26-09-08 10:29:33 at 19:56 after only 5 new records).
  Indexes therefore jump by 8 from time to time — identify records by time + content.
- Events: 0…85 (2025-06-25 … 2026-07-15), written on alarms/state changes (BHV, BLV, PLV, DOCA,
  SYSERR, …). Some flag values (e.g. `0x40`) are printed without a name.
- Timestamps: `YY-MM-DD HH:MM:SS`, battery local time, no time zone in the record. The battery
  clock runs **~9 min ahead** of the Cerbo (CEST): the newest `log` entry was stamped 17:19:43
  when the Cerbo showed 17:10:53. Battery times are kept verbatim in the export; the clock is
  never set (`time` is forbidden).
- Without a module number the records are the **master module's own** (module current/SOC match
  module 1, Total Coulomb 74000 mAh = one US3000C). Slaves: see the section above.

Record layout (same for history and event; history says `Rec Item Index`, event `Item Index`):

```
Rec Item Index  : 1797
Time            : 26-10-15 17:01:03
Voltage         : 50085       mV
Current         : -713        mA
Temperature     : 24500       mC
Percent         : 88          %
Total Coulomb   : 74000       mAH
Max Voltage     : 54000       mV
Base State      : Dischg
Volt. State     : Normal
Curr. State     : Normal
Tempr. State    : Normal
Coul. Status    : Normal
Power Events    : 0x0
Bat Events      : 0x0
Bat Protect ENA : BOV BHV BLV BUV …
Pwr Protect ENA : POV PHV PLV PUV …
System Fault    : 0x0
-----------------------------------------------
Battery  Volt     Curr     Tempr    Base State   Volt. State  Curr. State  Temp. State  Coulomb
0        3339     -713     23300    Dischg       Normal       Normal       Normal       89%
… 15 cell rows (0–14)
```

## `datalist <event|history> <start>` — table of many records (what BatteryView exports)

- Lists records `<start>` … last, **one line per record**, numbered **from 0**; `<start>` beyond the
  last record → `Invalid command`. `datalist history 0` = everything.
- Count of records: `stat` → `Data Items` (events) and `HisData Items` (history).
- Master only: `datalist 2 history 1790` → usage (datalist is not in the help's "Remote command"
  list). Slaves are read with `data <module> …` record by record.
- **No individual cells** — only lowest/highest cell voltage and temperature per record.
- Same indexes as `data` (an apparent offset of 8 between two reads was the ring buffer dropping
  a block of 8 in between).
- Full master history table (`datalist history 0`): 1796 rows, 606 KB, **104 s** with 112 Enter
  page answers. Full event table: 86 rows, 3.8 s.
- Every column except `Rec_chg/dsg_cur`, `Sys_Rec_chg/dsg_cur` and `ID Cur` can be derived
  exactly from the matching `data` record (checked on history 17:31:25 and events 0–85):
  `Vo`=Voltage, `Cu`=Current, `Tempr`=Temperature, `Tlow`/`Thigh`=min/max cell temperature,
  `Vlowest`/`Vhighest`=min/max cell voltage, the four states, `Per%`=Percent,
  `Events`=Power-event names + Bat-event names (e.g. `PHV BHV`), `SysErrCode` blank when
  System Fault is 0x0.
- Columns depend on firmware. B69.25 (this stack), history:
  `Item Time Vo(mV) Cu(mA) Tempr Tlow Thigh Vlowest Vhighest Base.St Volt.St Curr.St Temp.St Per%
  SysErrCode Rec_chg/dsg_cur(0.1A) Sys_Rec_chg/dsg_cur(0.1A) ID Cur ×15 (0.1A) Events` —
  the master also logs the current of every module ID 2…16. B69.19 (BatteryView sample):
  `Item Time Vo(mV) Cu(mA) Tempr Tlow Thigh Vlowest Vhighest Base.St Volt.St Curr.St Temp.St Per%
  Events SysErrCode`. Parse by header.
- History starts with `Save data every 1800 S`.

## BatteryView export format (real files from this stack, cable on each module, 2026-10-16)

Two `.txt` files per module, named `<barcode>_<event|history>_<YYYYMMDDhhmmss>.txt` (the `.data`
files next to them are BatteryView's own encrypted copies; support gets the `.txt` files).

- event file: `info`, `stat`, `pwr`, `datalist event 0`; history file: `info`, `stat`,
  `datalist history 0`.
- `info`, `stat`, `pwr` are the console bytes as received. The `datalist` part is rewritten with
  CRLF line ends; where the console paged, a line of 50 spaces remains — before rows 15, 31, 47, …
  (every 16 rows). History starts with `Save data every 1800 S`.
- The prompt between commands is often cut (`pylon_debstat`, `pylon_d`): the files are not
  byte-stable even between two BatteryView downloads. One of the eight files (M2 history) was
  broken (`info` twice, no table) and nobody noticed.
- On a module's own console the prompt is `pylon>`, `pwr` prints that module's detail
  (`CFetState`, `Power  N`, voltage, statuses, protections; `Charge Sec.` / `Discharge Sec.`
  depending on the state), and the table has values in Rec_chg/dsg_cur, Sys_Rec_chg/dsg_cur
  (always `0 / 0` on slaves) and ID Cur (always 0 on slaves).

Reproduced through the master (`pylontech_export.py`, compared with these files):
- master: the `datalist` part is **byte-identical** after the same rewrite (86 events, 1795
  history rows);
- slaves: `info N` = the module's `info` (same 19 lines), `stat N` = its `stat` (same 120 fields),
  `pwr N` = its `pwr` (same detail; `Charge Times` / `Charge Sec.` show 0 through the master);
  table rows rebuilt from `data N …`: **all value columns identical** (298 rows compared);
  Rec_chg/dsg_cur, Sys_Rec and ID Cur are `-` (not readable through the master).

## Reading slaves record by record: cut replies

About 1 % of `data N …` replies are cut short by the master: the truncated text is followed
directly by `pylon_debug>` (no line break). **The rest of that answer arrives as the reply to the
next command** (a bare Enter does not flush it). A reply is therefore only accepted when it carries
the record asked for — the right `Item Index`, a `Time`, and the full cell table — otherwise it is
rejected and the record read again (typically: cut reply, stray rest, then the good reply).

## `log`

Text log of the master (`ModID : BMM`), **newest first**, only 32 entries (index 31…0). On
2026-10-15 it covered just ~18 minutes of charge/discharge toggling around 0 A, e.g.:

```
 Index   : 31
 Time    : 26-10-15 17:19:43
 ModID   : BMM
 Code    : 0
 Info    : The device start discharging.
```

11 pages, ~2.2 s with Enter paging. Not part of the BatteryView files; not exported.

## Time for a full export (measured 2026-10-16, 4× US3000C)

Master: `datalist` tables ~2 min. Slaves: `data N …` record by record, 0.6 s reply + 0.2 s pause
(tested against 1.2 s: same bytes) + re-reads of cut replies ≈ 0.9 s per record → ~30 min per
module (~1 800 history + ~100–230 events). Whole stack: **~1 h 25 min**.
