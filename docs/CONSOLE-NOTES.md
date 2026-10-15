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
  when the Cerbo showed 17:10:53. The archive must store the battery time verbatim and record the
  observed offset at sync time; the clock is never set (`time` is forbidden).
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

## BatteryView export format (sample supplied 2026-10-15, local only)

Two files per module, named `<barcode>_<event|history>_<YYYYMMDDhhmmss>.txt`. Each is the **verbatim
console transcript** (mixed `
`/`
` line endings kept) of:

```
info
@ … info reply … Command completed successfully
$$pylon_debug>stat
@ … stat reply …
$$pylon_debug>datalist event 0          (or: datalist history 0)
@ … table …
Command completed successfully
$$
pylon_debug>
```

No `Press [Enter]` text appears. The console sends `
Press [Enter] to be continued,other key
to exit` + 50 spaces + `` before the next row; BatteryView's file has `
` + 50 spaces +
`
` instead, and table rows end in `
` where the console sends `
`. Matching the
file byte for byte needs a BatteryView export from this stack (firmware B69.25) to compare.
BatteryView reads the module the cable is plugged into (`Device address : 1`). Producing the same
file for a **slave through the master** is not possible verbatim (no remote `datalist`); see
ARCHITECTURE §4.11.

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

11 pages, ~2.2 s with Enter paging. Low archive value unless polled often.

## Time budget for a full download

Per module ~1800 history + ~85 events; 0.4 s per record on the master, 0.6 s on a slave, plus the
1.2–2 s pause between commands → roughly 1 h per module, **~4–5 h for the whole 4-module stack** on
the first full sync. Afterwards only new records (4 modules × 1 per 30 min). The pause may be
shorter (untested).
