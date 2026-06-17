# Instrument Samba Share Setup

## Background

Picarro Linux instruments (PI-series, e.g. NEDS2155) store data in two locations:

| Location | Contents |
|---|---|
| `/home/picarro/I2000/Archive/Data/` | Historical data — zipped h5 files organised into `YYYY-MM-DD/Datalog_Private/` subfolders. Files land here after the instrument archives them (typically within 24h of collection). |
| `/home/picarro/I2000/Log/DataLogger/DataLog_Private/` | Live data — individual h5 files being written in real time, not yet archived. |

The default Samba configuration on these instruments exposes only the `Archive/Data/` folder as the `Data` share. This means the most recent data (last few hours up to ~24h) is not visible over the network until it gets archived.

---

## Required Setup — One-Time Per Instrument

### Step 1 — Create a symlink inside the Archive folder

Log into the instrument (SSH or local terminal) and run:

```bash
ln -s /home/picarro/I2000/Log/DataLogger /home/picarro/I2000/Archive/Data/DataLogger
```

This makes the live DataLogger folder appear as a subfolder inside the existing `Data` share, without changing the share path or requiring the Windows client to remount anything.

Verify it worked:
```bash
ls -la /home/picarro/I2000/Archive/Data/
```
You should see `DataLogger -> /home/picarro/I2000/Log/DataLogger` in the listing.

### Step 2 — Update smb.conf to allow symlink traversal

Open the Samba config:
```bash
sudo nano /etc/samba/smb.conf
```

Find the `[Data]` share section and make sure it includes these two lines:
```ini
[Data]
   path = /home/picarro/I2000/Archive/Data
   read only = yes
   browseable = yes
   valid users = picarro
   follow symlinks = yes
   wide links = yes        ← add this line
```

`wide links = yes` is required because the symlink points outside the share's own directory tree. Without it Samba silently refuses to follow the link.

### Step 3 — Restart Samba

```bash
sudo systemctl restart smbd
```

### Step 4 — Verify from Windows

On the Windows client, open Explorer and browse to `Y:\` (or whichever drive letter the Data share is mapped to). You should now see:

```
Y:\
├── 2025-10-23\          ← archived data (unchanged)
├── 2025-10-24\
├── ...
├── YYYY-MM-DD\          ← most recent archived day
└── DataLogger\          ← NEW — live data folder
    └── DataLog_Private\
        └── NEDS2155-20260617-...Z-DataLog_Private.h5
```

---

## Result

- The Windows drive mapping (`Y:\`) does not need to change.
- The Pi Viewer app (`pi_viewer.py`) can scan `Y:\` and find both archived and live data under the same path.
- No additional shares, no additional drive letters.
- Adding the symlink is non-destructive — removing it restores the original state with no side effects.

---

## Notes

- The `-RDF` folders (e.g. `2025-10-23-RDF`) in the archive contain RDF-format data for a different instrument subsystem. The Pi Viewer app ignores these by design.
- The `RDF.zip` file sometimes visible in the archive root is also RDF data — not the H2O2/H2O/CH4 Datalog data. The app ignores it.
- If the instrument is reinstalled or the OS is reimaged, the symlink will need to be recreated (Step 1 above). The smb.conf change may also be lost and need to be reapplied.
- Tested on: NEDS2155 (Ubuntu, Samba). Should apply to all PI-series instruments with the same directory structure.
