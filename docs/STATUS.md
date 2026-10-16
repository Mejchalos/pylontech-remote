# Status — Pylontech Remote (2026-10-16)

**Goal:** get the logs of a Pylontech battery remotely and file a warranty claim — the per-module
BatteryView `.txt` files (event + history) that Pylontech support gets — with access to the
**master's console only** (through a Victron Cerbo GX). Live data and counters are extras.
A history archive beyond what the battery stores itself is **not** a goal.

## What works (verified on one stack)

Test stack: 4× US3000C, firmware **B69.25.0.0**, Venus OS v3.81 on a Cerbo GX, CH340 USB cable.

| Part | State |
|---|---|
| **Logs for a warranty claim** — dashboard button → one ZIP, per module `<barcode>_event_<stamp>.txt` + `<barcode>_history_<stamp>.txt` | **works**, full stack in ~1 h 25 min, no record missing |
| Compared with real BatteryView files of the same stack (cable on each module) | **master**: tables byte-identical (1 881 rows); **slaves**: every value column identical (4 131 rows); 3 columns `-` (see below) |
| Download of the ZIP from the dashboard (LAN) | works; through VRM not verified yet |
| Live dashboard (whole stack incl. cells every 8 s, auto-off 30 min) | works |
| Module counters (`stat`, ~120 values per module), BHV counter increases | works |
| Read-only safety: one allow-list for every command, tests | works (38 tests) |

## What the export cannot reproduce through the master

For the master everything is identical. For the other modules (read through the master):

- **Tables are rebuilt** from the module's own records (`data N event|history i`) because the
  master does not relay `datalist`. Values are the module's own; layout identical.
- **Rec_chg/dsg_cur, Sys_Rec_chg/dsg_cur, ID Cur** are not readable through the master → `-`.
  On the module itself Sys_Rec is always `0 / 0` and ID Cur always 0; Rec_chg/dsg varies.
- `pwr N` shows `Charge Times` and `Charge Sec.` as 0 (on the module itself they have values).
- Command echoes are the truthful ones (`info 2`, prompt `pylon_debug>`), and the table carries a
  line `[reconstructed by pylontech-remote …]` (decided 2026-10-16).

Fallback if this is not acceptable: the cable moved to each module once (customer, guided by
phone) gives verbatim files — designed (ARCHITECTURE §6), not built.

## What blocks real use

1. **Does Pylontech accept the reconstructed slave files?** Their support most likely runs the
   files through their own software. Missing columns, the marker line or the echoes may break it.
   → **ask Pylontech** (draft: [FOR-PYLONTECH-SUPPORT.md](FOR-PYLONTECH-SUPPORT.md)).
2. **Other firmwares / models are untested.** Known differences: B69.19 has another `datalist`
   column layout (our rebuilt tables use the B69.25 layout); US3000D reportedly refuses
   `info N`/`stat N` for slaves (node-red-contrib-pylontech-health); whether older firmware relays
   `data N …` is unknown. → collect samples (read-only check script, not built yet).
3. **Cable and installation are not robust yet.**
   - Test cable CH340: the udev rule matches one USB socket (no serial number); another socket or
     a hub → Venus OS starts probing the port again. FTDI (rule by serial) documented, untested.
   - The rule lives in `/etc` → **gone after a Venus OS update** (no restore at boot yet).
   - Installation is manual (scp + Node-RED import); the old `install.sh` is legacy and unsuitable.

## Notes from operation

- Export: ~0.9 s per record of a slave module (~30 min per module), master ~2 min. Live is
  stopped while it runs. ~1 % of slave reads are cut short by the master and read again.
- Observed once (2026-10-15 22:17–22:27): modules 2 and 4 wrote extra history records while being
  read by test exports. Not seen in the full export of 2026-10-16. Harmless; watched.
- The battery clock runs ~9 min ahead of the Cerbo; it is never set (forbidden command).
- One of the eight BatteryView files of the same stack was broken (M2 history: `info` twice,
  no table) — the export produced it complete.

## Next steps (proposed order)

1. Ask Pylontech about the reconstructed files (user).
2. Check the ZIP download through VRM.
3. FTDI cable; then boot persistence: rule restored from `/data` at every boot (`/data/rc.local`).
4. Installer / uninstaller instead of the manual steps.
5. Read-only compatibility check script → samples from other firmwares/models.
6. Only if Pylontech requires verbatim slave files: phone-guided cable move.
