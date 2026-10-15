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
| `datalist [event/history/…][item/bat][batnun][volt/curr/temp/coul][item]` | Show recorded data — `datalist`, `datalist history`, `… item 1`, `… bat 1` all return usage; full argument meaning unknown, not pursued |
| `log` | Log information show — see below |

`data` is also listed under "Remote command" (as are `info`, `stat`, `config`, `soh`); how a
remote module is addressed from the console is not known yet.

## `data history N` / `data event N`

- **Index 1 = oldest, highest index = newest.** An index past the end returns
  `Invalid command or fail to excute.`
- History: one record every **30 min**. On 2026-10-15 17:01 the range was 1…1797
  (1 = 2026-09-08 06:59:33), i.e. ~37 days. Whether index 1 shifts once the buffer is full
  (ring buffer) is not verified yet — re-read index 1 and the max after the next record.
- Events: 1…85 (2025-06-25 … 2026-07-15), written on alarms/state changes (BHV, BLV, PLV, DOCA,
  SYSERR, …). Some flag values (e.g. `0x40`) are printed without a name.
- Timestamps: `YY-MM-DD HH:MM:SS`, battery local time, no time zone in the record. The battery
  clock runs **~9 min ahead** of the Cerbo (CEST): the newest `log` entry was stamped 17:19:43
  when the Cerbo showed 17:10:53. The archive must store the battery time verbatim and record the
  observed offset at sync time; the clock is never set (`time` is forbidden).
- The records hold the **master module's own** values (module current/SOC match module 1, Total
  Coulomb 74000 mAh = one US3000C). Reading slave history from the master console is not solved.

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

~1800 history + ~85 events at 0.4 s per record plus the 1.2–2 s pause between commands
→ roughly 50–75 min for the master's history. The pause may be shorter for master-local data
(untested).
