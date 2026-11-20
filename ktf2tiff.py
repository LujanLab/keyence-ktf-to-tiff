"""Convert Keyence BZ-X .ktf images to full-resolution TIFF.

A .ktf file ("KTL2" header) holds a tiled JPEG pyramid, a thumbnail JPEG and
an XML block with acquisition metadata. This script reassembles the
full-resolution level, crops the tile padding, and writes:

  <name>.tif            RGB, 8 bit, LZW (lossless). Opens in Windows Photos,
                        Fiji/ImageJ (scale set in microns), QuPath, Python.
  <name>_metadata.xml   Keyence acquisition metadata, verbatim.
  <name>_gray.tif       (with --gray) the pseudocolored channel only, as a
                        single-channel 8-bit image for quantification.

The tiles are JPEG inside the .ktf, so the pixel values written are exactly
what the Keyence software stored; nothing is lost in the TIFF step.

Usage:
  python ktf2tiff.py FILE_OR_FOLDER [...] [-o OUTDIR] [--gray] [--overwrite]
Folders are searched recursively for *.ktf.
"""

import argparse
import io
import math
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

MAGIC = b"KTL2"
PSEUDO_TO_INDEX = {"Red": 0, "Green": 1, "Blue": 2}


class KtfError(Exception):
    pass


def read_header(buf):
    if buf[:4] != MAGIC:
        raise KtfError("not a KTL2/.ktf file (magic %r)" % buf[:4])
    data_off = struct.unpack_from("<I", buf, 0x04)[0]
    index_off = struct.unpack_from("<Q", buf, 0x10)[0]
    tile = struct.unpack_from("<I", buf, 0x24)[0]
    width, height = struct.unpack_from("<II", buf, 0x30)
    thumb_off = struct.unpack_from("<Q", buf, 0x40)[0]
    thumb_len = struct.unpack_from("<Q", buf, 0x50)[0]
    xml_off = struct.unpack_from("<Q", buf, 0x60)[0]
    xml_len = struct.unpack_from("<Q", buf, 0x68)[0]
    return dict(data_off=data_off, index_off=index_off, tile=tile,
                width=width, height=height, thumb_off=thumb_off,
                thumb_len=thumb_len, xml_off=xml_off, xml_len=xml_len)


def pyramid_levels(width, height, tile):
    """Tile grid per level, full resolution first, halving until 1x1."""
    levels, k = [], 0
    while True:
        nx = math.ceil(width / 2 ** k / tile)
        ny = math.ceil(height / 2 ** k / tile)
        levels.append((nx, ny))
        if nx == 1 and ny == 1:
            return levels
        k += 1


def read_full_resolution(buf, h):
    tile = h["tile"]
    levels = pyramid_levels(h["width"], h["height"], tile)
    n_entries = sum(nx * ny for nx, ny in levels)
    if h["index_off"] + 16 * n_entries > h["thumb_off"]:
        raise KtfError("tile index does not fit the expected pyramid layout")
    nx, ny = levels[0]
    out = np.zeros((ny * tile, nx * tile, 3), dtype=np.uint8)
    for i in range(nx * ny):
        off, length, _ = struct.unpack_from("<QII", buf, h["index_off"] + 16 * i)
        start = h["data_off"] + off
        im = Image.open(io.BytesIO(buf[start:start + length])).convert("RGB")
        if im.size != (tile, tile):
            raise KtfError("tile %d is %s, expected %dx%d" % (i, im.size, tile, tile))
        r, c = divmod(i, nx)
        out[r * tile:(r + 1) * tile, c * tile:(c + 1) * tile] = np.asarray(im)
    return out[:h["height"], :h["width"]]


def read_metadata(buf, h):
    raw = buf[h["xml_off"]:h["xml_off"] + h["xml_len"]]
    text = raw.decode("utf-8-sig", errors="replace")
    meta = {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return text, meta

    def double(el):
        # Keyence stores System.Double values as their 64-bit integer bit pattern.
        return struct.unpack("<d", struct.pack("<q", int(el.text)))[0]

    def find(path):
        el = root.find(path)
        return el if el is not None and el.text is not None else None

    el = find(".//Image/Calibration")
    if el is not None:
        meta["um_per_px"] = double(el) / 1000.0  # stored in nm per pixel
    for key, path in [("pseudocolor", ".//Parameter/PseudoColor"),
                      ("channel", ".//Shooting/Channel"),
                      ("lens", ".//Lens/LensName"),
                      ("is_overlay", ".//Image/IsOverlay")]:
        el = find(path)
        if el is not None:
            meta[key] = el.text.strip()
    el = find(".//Parameter/ExposureTime")
    if el is not None:
        num, den = el.find("Numerator"), el.find("Denominator")
        if num is not None and den is not None and int(den.text):
            meta["exposure_s"] = int(num.text) / int(den.text)
    return text, meta


def write_tiff(path, img, um_per_px, description_extra=""):
    kwargs = dict(compression="lzw", imagej=True,
                  metadata={"unit": "um"})
    if um_per_px:
        px_per_um = 1.0 / um_per_px
        kwargs["resolution"] = (px_per_um, px_per_um)
    if img.ndim == 3:
        kwargs["photometric"] = "rgb"
    else:
        kwargs["photometric"] = "minisblack"
    tifffile.imwrite(str(path), img, **kwargs)


def convert(src, outdir, gray, overwrite, log=print):
    dst = outdir / (src.stem + ".tif")
    if dst.exists() and not overwrite:
        log("skip (exists): %s" % dst)
        return
    buf = src.read_bytes()
    h = read_header(buf)
    img = read_full_resolution(buf, h)
    xml_text, meta = read_metadata(buf, h)
    um = meta.get("um_per_px")

    outdir.mkdir(parents=True, exist_ok=True)
    write_tiff(dst, img, um)
    (outdir / (src.stem + "_metadata.xml")).write_text(xml_text, encoding="utf-8")

    info = "%dx%d px" % (h["width"], h["height"])
    if um:
        info += ", %.4f um/px" % um
    if meta.get("pseudocolor"):
        info += ", pseudocolor %s" % meta["pseudocolor"]
    log("wrote %s  (%s)" % (dst, info))

    if gray:
        idx = PSEUDO_TO_INDEX.get(meta.get("pseudocolor", ""))
        if idx is None or meta.get("is_overlay") == "True":
            log("  no --gray for %s: it is an overlay or has no single pseudocolor" % src.name)
        else:
            gdst = outdir / (src.stem + "_gray.tif")
            write_tiff(gdst, np.ascontiguousarray(img[..., idx]), um)
            log("wrote %s  (%s channel)" % (gdst, meta["pseudocolor"].lower()))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("inputs", nargs="+", help=".ktf files or folders")
    p.add_argument("-o", "--outdir", help="output folder (default: next to each .ktf)")
    p.add_argument("--gray", action="store_true",
                   help="also write the pseudocolored channel as single-channel 8-bit TIFF")
    p.add_argument("--overwrite", action="store_true", help="replace existing outputs")
    args = p.parse_args(argv)

    files = []
    for s in args.inputs:
        path = Path(s)
        if path.is_dir():
            files += sorted(path.rglob("*.ktf"))
        elif path.suffix.lower() == ".ktf":
            files.append(path)
        else:
            print("ignored (not .ktf or folder): %s" % s)
    if not files:
        print("no .ktf files found")
        return 1

    failed = 0
    for f in files:
        outdir = Path(args.outdir) if args.outdir else f.parent
        try:
            convert(f, outdir, args.gray, args.overwrite)
        except (KtfError, OSError, struct.error) as e:
            failed += 1
            print("FAILED %s: %s" % (f, e))
    print("done: %d converted or skipped, %d failed" % (len(files) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
