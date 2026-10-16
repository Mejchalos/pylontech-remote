# Draft: note for Pylontech support

*Draft for the user to adapt — nothing has been sent. Short technical description of how the
attached logs were produced, to ask whether support can process them.*

---

Subject: Battery logs read remotely through the master module — usable for warranty claims?

Hello,

we read Pylontech logs remotely, without a technician on site, and would like to know whether you
can process them for warranty claims.

**How they are produced.** A Victron Cerbo GX is connected to the RS232 **console of the master
module** (115200 baud). A program on it sends only read commands and saves, for every module, the
same two text files BatteryView saves (`<barcode>_event_<time>.txt`, `<barcode>_history_<time>.txt`:
`info`, `stat`, `pwr`, `datalist event|history 0`).

- **Master module:** identical to BatteryView's files (compared byte by byte with files BatteryView
  saved from the same battery).
- **Other modules:** the master does not relay `datalist`, so each table is rebuilt row by row from
  the module's own records, read through the master with `data <module> event|history <i>`.
  Compared with BatteryView files saved with the cable on each module, every value column is
  identical (time, voltages, currents, temperatures, lowest/highest cell, states, SOC, events,
  error code). Three columns cannot be read this way and are `-`: `Rec_chg/dsg_cur(0.1A)`,
  `Sys_Rec_chg/dsg_cur(0.1A)`, `ID Cur`. The headers show the commands actually used
  (`info 2`, `stat 2`, `pwr 2`), and the table has one marker line
  `[reconstructed by pylontech-remote …]`.
- The `.data` files BatteryView writes next to the `.txt` files are not produced.

Tested on US3000C, firmware B69.25.0.0.

**Questions**

1. Can you process the files of the non-master modules in this form?
2. If not: which parts are required — the three columns, the `.data` files, the exact command
   headers, no marker line?
3. Is there a documented way to read a slave module's `datalist` through the master console?

Thank you.
