# Playable Giganotosaurus for Dino Crisis 2

Play as the Giganotosaurus in Dino Crisis 2's Extra Crisis modes. It replaces the playable
T-Rex in the Dino Colosseum and in Dino Duel, and on the character select screen. Optionally,
the Colosseum raptor can get the Dino Duel "Ultra Raptor" skin too.

These are Python scripts that build the mod from **your own copy of the game**. No game data is
included. There are two patchers:

- `pc_patch.py`: the PC release (Steam).
- `psx_patch.py`: PlayStation disc images (.cue/.bin), for use on an emulator or console.

> **Just want the PC files?** Ready-made drop-in files are on NexusMods:
> **[Playable Giganotosaurus on NexusMods](https://www.nexusmods.com/dinocrisis2/mods/7)**.
> You don't need Python or these scripts to use them.

## What changes

Where the T-Rex was, you get the Giganotosaurus:

- **Colosseum:** the playable T-Rex (`WEP_PR10.DAT`).
- **Dino Duel:** player 1 (`KOF_P10P.DAT`) and player 2 (`KOF_P11P.DAT`).
- **Character select screen:** the preview model (`M_TITLE.DAT`, `M_E10.TEX`).
- **Colosseum raptor (optional):** with `--ultra-raptor`, the raptor (`WEP_PR0D.DAT`) and its
  preview (`M_E00.TEX`) take the texture and palette of the Ultra Raptor from Dino Duel
  (`KOF_P01P.DAT`), which uses the same model.

For each of these, the mod changes:

- **Model and texture:** the T-Rex's model and texture are replaced by the Giganotosaurus's.
  You can pick its normal face (the default) or its burnt face.
- **Sounds:** the Giganotosaurus's roars and footsteps replace the T-Rex's. Moves that use a
  Giganotosaurus animation also play that animation's own sounds, timed to its poses. Which
  Giganotosaurus sound replaces each T-Rex sound was chosen by ear.
- **Animations:** the Giganotosaurus's own walk, walking backwards, run, roar and death. The
  other moves use the T-Rex's motion, scaled up to its size: the bites (so the head still
  reaches the ground), the special attack, flinches, staggers, hop back and the other death.
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

   The first install backs up the original files it replaces to `Data\giga_mod_backup`. It
   then copies the patched files into `Data`. The patched files are also written to `output\`
   next to the scripts.
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
| `--map=SLOT:GIGA,...` | Play these Giganotosaurus animations in these T-Rex slots for this run, e.g. `--map=24:21`. `A+B+C` plays several one after another in one slot |
| `--trex-slots=SLOT,...` | Keep the T-Rex animation in these slots for this run |
| `--normal-face` | Use the Giganotosaurus's normal face texture (the default) |
| `--burnt-face` | Use its burnt face texture (`E41.TEX`) |
| `--face-tex=FILE` | Use the face texture from another `E41.TEX`-style file |
| `--ultra-raptor` | Give the Colosseum raptor the Dino Duel Ultra Raptor skin |
| `--wav-map-roars` | Send the roars through `REX_TO_GIGA` too, instead of the Giganotosaurus's own roar |

`pc_patch.py` also takes `--out DIR`, `--install` and `--restore`, as described above.

To change which Giganotosaurus animation plays for each move for good, edit `MAPPING` in
`giga_anims.py`.

## How it works

Both patchers read the Giganotosaurus from the game's own `E40.DAT` and rebuild the T-Rex files
around it:

- **Model:** transplanted into the T-Rex's memory slot. The Giganotosaurus skeleton is the
  T-Rex's skeleton scaled by 1.38, and both have 20 parts in the same hierarchy, so the T-Rex's
  animations and game code still fit it.
- **Animations:** the Giganotosaurus's frames are resampled to the length of the T-Rex move they
  replace. Attack frames are lined up so a strike lands when the game expects it. Each move keeps
  the T-Rex's timing, root motion and hit data. Its sound cues come from the Giganotosaurus
  animation, retimed the same way.
- **Hit spheres:** worked out with forward kinematics. Each sphere is placed where the T-Rex's was
  in the world on the same frame, then expressed relative to the Giganotosaurus's bone.
- **Sounds:** the Giganotosaurus's sound bank is used. It is mapped onto the T-Rex's sound event
  table, which the game code triggers by event number. Events only the Giganotosaurus has are
  added, so its animations' sound cues all play. Which T-Rex sound becomes which
  Giganotosaurus sound is set by `REX_TO_GIGA` in `character.py`, for both versions; the roars
  use the Giganotosaurus's own. On PlayStation, the samples' sound RAM addresses are also moved
  to where the T-Rex's samples are loaded.
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

Thanks to:

- **[VictowiaUwU](https://github.com/VictowiaUwU)** for the PlayStation sound fix, the sound
  choices, the roar and special attack animations, the Ultra Raptor skin and the burnt face
  option.
- **[SpikeTheEditor](https://github.com/SpikeTheEditor)** for testing and feedback.

Dino Crisis 2 is © Capcom. This project is an unofficial fan mod. It is not affiliated with or
endorsed by Capcom.

## License

GPL-3.0. See [LICENSE](LICENSE).
