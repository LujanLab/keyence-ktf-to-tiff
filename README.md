# keyence-ktf-to-tiff

Converts Keyence BZ-X `.ktf` scans into full-resolution TIFFs that open in Windows Photos, Fiji/ImageJ, QuPath and Python.

## Quick start (Windows, no Python needed)

1. Download `KTF2TIFF.exe` from the [Releases](../../releases) page.
2. Double-click it. A folder picker opens. Pick a folder of `.ktf` files, add more folders if needed, and click **Convert**.

You can also drag folders or `.ktf` files onto the exe to pre-fill the list.

## Output

For each `name.ktf`, the converter writes:

| File | Contents |
|---|---|
| `name.tif` | RGB, 8 bit, LZW compressed (lossless). The pixel size is stored in the file, so Fiji opens it scaled in microns. |
| `name_metadata.xml` | The Keyence acquisition metadata (objective, exposure, gain, channel, pseudocolor, stage position), copied unchanged. |
| `name_gray.tif` | Optional. The pseudocolored channel alone (green for a "Green" channel, and so on) as a single-channel 8-bit image, for intensity measurements. Overlay images get no gray version. |

## Command line

```
pip install -r requirements.txt
python ktf2tiff.py FILE_OR_FOLDER [...] [-o OUTDIR] [--gray] [--overwrite]
```

The script searches folders recursively. `KTF2TIFF.exe --cli ...` takes the same arguments and opens no window.

## What is inside a .ktf

The layout below comes from reverse engineering files saved by the BZ-X analyzer. Keyence does not publish the format.

- A `KTL2` magic and header. The header holds the image width and height (u32 at 0x30 and 0x34), the tile size (u32 at 0x24, 512), the start of the tile data (u32 at 0x04) and the start of the tile index (u64 at 0x10).
- A pyramid of 512 x 512 JPEG tiles. The full-resolution level comes first, then each level halves until a single tile remains. Tiles are in row-major order, and edge tiles are padded.
- A tile index of 16-byte entries: an offset from the start of the tile data, a length, and a constant.
- A thumbnail JPEG (offset and length at 0x40 and 0x50).
- An XML metadata block (offset and length at 0x60 and 0x68). Keyence stores `System.Double` values as their 64-bit integer bit pattern. `Calibration` is in nm per pixel.

## Limits

- **Lossy tiles.** The tiles inside a `.ktf` are JPEG, so their pixels are already lossy. The TIFF holds exactly those pixels and adds no loss of its own.
- **8-bit only.** Files from an 8-bit camera mode have no higher bit depth to recover.
- **Small values in unused channels.** JPEG compression leaves small non-zero values in the channels a pseudocolor image does not use. Use the gray output for measurements.
- **Tested layout.** The converter has been tested on single-plane, stitched fluorescence scans. It checks the file layout and reports an error if a file does not match, for example a z-stack or a different tile size.

## Building the exe

Run `build_exe.bat`. It needs Python 3.9 or later and an internet connection to install PyInstaller and the dependencies into a temporary virtual environment.
