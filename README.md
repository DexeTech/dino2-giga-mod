# Playable Giganotosaurus for Dino Crisis 2

Play as the Giganotosaurus in Dino Crisis 2's Extra Crisis modes. It replaces the playable
T-Rex in the Dino Colosseum and in Dino Duel, and on the character select screen.

These are Python scripts that build the mod from **your own copy of the game**. No game data is
included. There are two patchers:

- `pc_patch.py`: the PC release (Steam).
- `psx_patch.py`: PlayStation disc images (.cue/.bin), for use on an emulator or console.

> **Just want the PC files?** Ready-made drop-in files are on NexusMods: **NEXUS_MODS_URL**.
> You don't need Python or these scripts to use them.

## What changes

Where the T-Rex was, you get the Giganotosaurus:

- **Colosseum:** the playable T-Rex (`WEP_PR10.DAT`).
- **Dino Duel:** player 1 (`KOF_P10P.DAT`) and player 2 (`KOF_P11P.DAT`).
- **Character select screen:** the preview model (`M_TITLE.DAT`, `M_E10.TEX`).

For each of these, the mod changes:

- **Model and texture:** the T-Rex's model and texture are replaced by the Giganotosaurus's.
- **Sounds:** the Giganotosaurus's roars and footsteps replace the T-Rex's.
- **Animations:** the Giganotosaurus's own walk, walking backwards, run, bites, roars and death.
  The moves it has no animation for use the T-Rex's motion, scaled up to its size: the charge,
  turns, flinches, hop back, running bites and the other death.
- **Hit spheres:** attacks hit where the T-Rex's did.

Known limitations:

- **Camera and collision:** the camera distance and collision size are still the T-Rex's. They
  are set in the game's program code, which these scripts don't touch.
- **Preview lighting:** the model on the character select screen is lit a little flatter than
  in game. The Giganotosaurus only fits in the preview's memory slot without its lighting
  normals.

## Requirements

- Python 3.8 or newer. There are no other packages to install.
- **PC:** the game installed, with the original, unmodified data files.
- **PlayStation:** a Dino Crisis 2 disc image in .cue/.bin format. Tested with the USA release
  (SLUS-01279). Other releases are found by file name and should work if their data matches.

## PC

1. Find the game's `Data` folder. In Steam, right-click Dino Crisis 2, then choose
   **Manage > Browse local files**. The data is in `english\Data`; if you play in Japanese,
   use `japanese\Data`.
2. Build and install the mod:

   ```
   python pc_patch.py "C:\...\Dino Crisis 2\english\Data" --install
   ```

   The first install backs up the five original files to `Data\giga_mod_backup`. It then copies
   the patched files into `Data`. The patched files are also written to `output\` next to the
   scripts.
3. Start the game. In Extra Crisis, choose the T-Rex.

To remove the mod:

```
python pc_patch.py "C:\...\Dino Crisis 2\english\Data" --restore
```

This puts the backed-up originals back. Steam's **Verify integrity of game files** does the
same.

Without `--install`, the patcher only writes the files to `output\` (or the folder you give with
`--out DIR`), and you can copy them into `Data` yourself.

## PlayStation

```
python psx_patch.py "Dino Crisis 2 (USA).cue"
```

This writes a patched track 1, `Dino Crisis 2 (USA) (Giga) (Track 1).bin`, and a new cue,
`Dino Crisis 2 (USA) (Giga).cue`, next to the original. The new cue uses the original audio
track. Load the new .cue in your emulator.

- **Your original image is never modified.**
- **Other image formats:** convert them to .cue/.bin first. For a CHD, run
  `chdman extractcd -i game.chd -o game.cue`.
- **Output name:** you can give your own output name as a second argument:
  `python psx_patch.py game.cue "out (Track 1).bin"`.

The patched files are rewritten in place on the disc image, using the same sectors and the same
file sizes. The sector error-correction data (EDC/ECC) is regenerated, so the image stays valid
for emulators and disc burning.

## Options

Both patchers accept these options:

| Option | Effect |
| --- | --- |
| `--trex-anims` | Keep the T-Rex's animations, scaled up to the Giganotosaurus's size, instead of its own |
| `--keep-trex-sounds` | Keep the T-Rex's sounds |
| `--no-root-scale` | Keep the T-Rex animations' body height instead of raising it to the Giganotosaurus's hips (it then sinks into the floor) |
| `--no-hitbox-scale` | Keep the T-Rex's hit spheres exactly as they are |
| `--scale-hitboxes` | Scale the hit spheres with the body; they then reach past enemies |
| `--no-menu` | Leave the character select screen alone |
| `--no-duel` | Leave the Dino Duel files alone |

`pc_patch.py` also takes `--out DIR`, `--install` and `--restore`, as described above.

To change which Giganotosaurus animation plays for each move, edit `MAPPING` in
`giga_anims.py`.

## How it works

Both patchers read the Giganotosaurus from the game's own `E40.DAT` and rebuild the T-Rex files
around it:

- **Model:** transplanted into the T-Rex's memory slot. The Giganotosaurus skeleton is the
  T-Rex's skeleton scaled by 1.38, and both have 20 parts in the same hierarchy, so the T-Rex's
  animations and game code still fit it.
- **Animations:** the Giganotosaurus's frames are resampled to the length of the T-Rex move they
  replace. Attack frames are lined up so the bite lands when the game expects it. Each move keeps
  the T-Rex's timing, root motion, hit data and sound cues.
- **Hit spheres:** worked out with forward kinematics. Each sphere is placed where the T-Rex's was
  in the world on the same frame, then expressed relative to the Giganotosaurus's bone.
- **Sounds:** the Giganotosaurus's sound bank is used. It is mapped onto the T-Rex's sound event
  table, which the game code triggers by event number.
- **Character select preview:** the Giganotosaurus model is fitted into the T-Rex preview's fixed
  memory slot.
- **PlayStation only:** each file keeps its original sector count, because the disc loader
  relies on it.

The module docstrings describe the file formats in detail.

| File | Purpose |
| --- | --- |
| `pc_patch.py` | PC patcher (command line) |
| `psx_patch.py` | PlayStation disc image patcher (command line) |
| `character.py` | Data file container, LZSS compression, model transplant, scaling, hit spheres, sounds |
| `giga_anims.py` | Which Giganotosaurus animation replaces each T-Rex move, and the resampling |
| `skeleton_fk.py` | Forward kinematics for the 20-part skeletons |
| `menu_preview.py` | Character select preview model and texture |
| `cdimage.py` | ISO9660 file access and in-place rewriting of MODE2/2352 disc images |

## Credits

Dino Crisis 2 is © Capcom. This project is an unofficial fan mod. It is not affiliated with or
endorsed by Capcom.
