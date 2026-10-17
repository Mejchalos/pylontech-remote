# Pylontech RS232 console — protocol reference

Behaviour of the console as used by this project. Verified on US3000C, firmware B69.25.0.0,
through the console of the master module. Other firmwares may differ.

## Session

- 115200 8N1, no flow control, DTR and RTS low (the battery does not answer with them asserted).
- Prompt: `pylon_debug>` on the master's console, `pylon>` on a module's own console.
- A reply: echo of the command, `@`, the output, then `Command completed successfully`
  (or `Invalid command or fail to excute.` with usage), `$$`, the prompt.
  Line endings are mixed (`\r`, `\n\r`, `\r\r\n`).
- Long output pauses with `Press [Enter] to be continued,other key to exit`.
  **Enter continues; any other key aborts the output.**

## Commands used

All are read-only. Every other command is refused by `pylontech_remote/allowlist.py`.

| Command | Output |
|---|---|
| `pwr` | stack summary, one line per module |
| `pwr N` | detail of module N |
| `bat N` | cells of module N |
| `info [N]` | model, barcode, firmware, cell count |
| `stat [N]` | lifetime counters (~120); `Data Items` = event records, `HisData Items` = history records |
| `config` | protection thresholds |
| `data [N] event\|history I` | one stored record of module N (default: the master) |
| `datalist event\|history I` | all records from `I` as a table — of the module whose console this is (not relayed) |
| `log` | the master's text log, last 32 entries |

The module number goes right after the command (`data 2 history 15`). The `help` text does not
show this argument. A module that is not present answers `Target device is not present`.

## Stored records

- **History**: one record every 30 min, ring buffer of ~1800 records (~37 days). When full, the
  oldest records are dropped in blocks of 8, so indexes shift; records are identified by time and
  content.
- **Events**: written on alarms and state changes (BHV, BLV, DOCA, SYSERR, …).
- Index 0 is the oldest record. `data` and `datalist` use the same indexes. An index past the end
  returns `Invalid command`.
- Time stamps are the battery's local clock (`YY-MM-DD HH:MM:SS`, no time zone). The clock is
  read as is and never set.

`data` record (history says `Rec Item Index`, events `Item Index`):

```
Item Index      : 12
Time            : 25-03-03 07:41:20
Voltage         : 50085       mV
Current         : -713        mA
Temperature     : 24500       mC
Percent         : 88          %
...
Power Events    : 0x0
Bat Events      : 0x0
System Fault    : 0x0
-----------------------------------------------
Battery  Volt     Curr     Tempr    Base State   Volt. State  Curr. State  Temp. State  Coulomb
0        3339     -713     23300    Dischg       Normal       Normal       Normal       89%
... one row per cell
```

`datalist` prints one row per record without individual cells (only the lowest/highest cell
voltage and temperature). The columns depend on the firmware; the table is parsed by its header.
On B69.25 the master also logs `Rec_chg/dsg_cur`, `Sys_Rec_chg/dsg_cur` and the current of every
other module (`ID Cur`). All other columns follow from the matching `data` record.

## Reading the other modules through the master

`datalist` is not relayed: through the master it lists only the master's records. Other
modules are read either on their own console (cable moved, as BatteryView does) or record by
record through the master with
`data N event|history I` (~0.6 s per record, relayed by the master).

About 1 % of these replies are cut short by the master: the prompt follows the truncated text
directly, and the rest of the answer arrives as the reply to the next command. A reply is
therefore accepted only when it carries the requested index, a time and the full cell table;
otherwise the record is read again.

## BatteryView log files

BatteryView saves two text files per module, `<barcode>_event_<YYYYMMDDhhmmss>.txt` and
`<barcode>_history_<YYYYMMDDhhmmss>.txt`:

- event file: `info`, `stat`, `pwr`, `datalist event 0`;
- history file: `info`, `stat`, `datalist history 0` (starts with `Save data every 1800 S`).

`info`, `stat` and `pwr` are stored as received. The `datalist` part is stored with CRLF line
ends; where the console paged, a line of 50 spaces remains (before rows 15, 31, 47, …).

`pylontech_export.py` produces the same files:

- **master**: identical to BatteryView's files;
- **other modules**: `info N`, `stat N` and `pwr N` as the master relays them (same content as on
  the module's own console, except `Charge Times` / `Charge Sec.` which read 0); the table is
  rebuilt from the module's `data N …` records in the master's column layout. `Rec_chg/dsg_cur`,
  `Sys_Rec_chg/dsg_cur` and `ID Cur` cannot be read through the master and are written as `-`.
  The table carries a line `[reconstructed by pylontech-remote …]`.
