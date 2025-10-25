# AOSP Payload Dumper

A tool for extracting payload.bin files. Works on Windows, Linux, and macOS.

[Features](#features) • [Installation](#installation) • [Usage](#usage) • [Building](#building-from-source) • [FAQ](#faq)

---

## What is this?

A tool for extracting partition images (`.img` files) from payload.bin files.

Has both a GUI and command-line interface. You can extract system, boot, vendor, and other partitions as you whish.

**Useful if you're:**
- Making or maintaining custom ROMs
- Porting Android builds between devices
- Extracting boot.img for root
- Creating backups or recovery images

---

## Features

**Core stuff:**
- Extract all partition images from payloads
- Works with differential/incremental OTAs
- Can extract specific partitions instead of extracting everything
- Handles ZIP files - automatically finds payload.bin inside
- extract directly from HTTP/HTTPS/S3 without downloading first

**GUI:**
- Modern interface with dark mode and light mode 
- Real-time progress and logs
- Shows you what got extracted and file sizes
- Multi-threaded so it stays responsive
- Remembers your settings and file locations 

---

## Quick Start

### Windows Users (easiest way)

1. Download `PayloadDumper.exe` from [Releases](https://github.com/himanshuksr0007/aosp-payload-dumper/releases)
2. Run it (no installation needed)
3. Pick your payload.bin or .zip file
4. Choose where to save the extracted files
5. Hit "Start Extraction"
6. Done

### Linux/macOS or if you prefer running from source

```bash
# Clone it
git clone https://github.com/himanshuksr0007/aosp-payload-dumper.git
cd aosp-payload-dumper

# Install dependencies
pip install -r requirements.txt

# Generate protobuf files
protoc --python_out=. update_metadata.proto

# Launch GUI
python payload_gui.py

# Or use CLI
python payload_core.py your-payload.bin --out extracted/
```

---

## Installation

### Option 1: Windows Executable (recommended for Windows)

No Python needed.

1. Go to [Releases](https://github.com/himanshuksr0007/aosp-payload-dumper/releases)
2. Download `PayloadDumper.exe`
3. Run it

> Some antivirus tools flag PyInstaller executables. It's a false positive - you can add an exception if needed.

---

### Option 2: Run from Source

#### Install Python

**Windows:**
- Download From [python.org](https://www.python.org/downloads/)
- Make sure to check "Add Python to PATH"

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3 python3-pip
```

**macOS:**
```bash
brew install python3
```

#### Get the code

```bash
git clone https://github.com/himanshuksr0007/aosp-payload-dumper.git
cd aosp-payload-dumper
```

#### Install dependencies

```bash
pip install -r requirements.txt
```

This grabs:
- PyQt6 (for the GUI)
- protobuf (payload parsing)
- bsdiff4 (binary diffs)
- brotli, zstandard (compression libraries)
- fsspec (remote file support)

#### Generate protobuf files

You need the protoc compiler first.

**Windows:**
1. Download from [GitHub Releases](https://github.com/protocolbuffers/protobuf/releases)
2. Extract `protoc.exe`
3. Add to PATH or use the full path

**Linux:**
```bash
sudo apt install protobuf-compiler  # Ubuntu
sudo dnf install protobuf-compiler  # Fedora
```

**macOS:**
```bash
brew install protobuf
```

**Then generate the Python files:**
```bash

# Generate Python code
protoc --python_out=. update_metadata.proto
```

This creates `update_metadata_pb2.py` which is needed for parsing payloads.

#### Run it

**GUI:**
```bash
python payload_gui.py
```

**CLI:**
```bash
python payload_core.py --help
```

---

## Usage

### GUI Mode

#### Starting it up

**Windows executable:**
Just double-click `PayloadDumper.exe`

**From source:**
```bash
python payload_gui.py
```

#### How to extract

1. **Pick your file**
   - Click "Browse" next to "Payload/OTA File"
   - Choose your `payload.bin` or `.zip`
   - It'll auto-detect if it's valid

2. **Choose output folder**
   - Click "Browse" next to "Output Directory"
   - Pick where you want the extracted images

3. **Optional: Filter partitions**
   - Leave blank to get everything
   - Or type specific ones: `boot,system,vendor`
   - Comma-separated, no spaces

4. **Optional: Differential OTA**
   - Check this if you have an incremental update
   - You'll need the original images in an `old/` directory

5. **Extract**
   - Click "Start Extraction"
   - Watch the progress

6. **Check results**
   - Switch to "Results" tab
   - See what got extracted and file sizes
   - Click "Open Output Folder" to view

---

### CLI Mode

#### Basic usage

```bash
python payload_core.py <payload_file> [options]
```

#### Examples

**Extract everything:**
```bash
python payload_core.py payload.bin --out extracted/
```

**From an OTA zip:**
```bash
python payload_core.py update.zip --out extracted/
```

**Just specific partitions:**
```bash
python payload_core.py payload.bin --out extracted/ --images boot,system,vendor
```

**One partition:**
```bash
python payload_core.py payload.bin --out extracted/ --images boot
```

**Differential OTA:**
```bash
# Put original images in 'old/' first
python payload_core.py incremental-update.bin --out extracted/ --diff --old old/
```

**From a URL:**
```bash
python payload_core.py https://example.com/ota-update.zip --out extracted/
```

---

## Advanced Stuff

### Differential/Incremental OTAs

These updates only contain the differences between versions, not full images. To extract them:

1. Put the original partition images in an `old/` folder
2. Name them exactly as they appear in the payload (`boot.img`, `system.img`, etc.)
3. Run with the `--diff` flag:
   ```bash
   python payload_core.py incremental.bin --out extracted/ --diff --old old/
   ```

### Extracting from URLs

You can extract directly from HTTP/HTTPS/S3 without downloading:

```bash
python payload_core.py https://rom-server.com/update.zip --out extracted/
```

Works with HTTP/HTTPS, S3, Google Cloud Storage, and other fsspec-supported sources.

---

## Building Your Own Executable

If you want to create the standalone `.exe`:

```bash
# Install PyInstaller
pip install pyinstaller

# Build
pyinstaller --onefile --windowed --name PayloadDumper --add-data "update_metadata_pb2.py;." payload_gui.py
```

Output will be in `dist/PayloadDumper.exe` (Windows) or `dist/PayloadDumper` (Linux/macOS).

---

## Troubleshooting

### "No module named 'update_metadata_pb2'"

You forgot to generate the protobuf files:
```bash
protoc --python_out=. update_metadata.proto
```

### "Invalid magic header, not an payload"

Your file isn't a valid Android OTA payload. Make sure:
- You're using an actual file this is or does contains payload.bin
- File isn't corrupted

### "Cannot write to output directory"

Permission issues or disk full:
- Try running with admin/sudo
- Pick a different output folder
- Free up some space (payloads typically extract to 5-10GB)

### GUI won't start / "No module named PyQt6"

```bash
pip install --upgrade PyQt6
```

Or just use the standalone `.exe` which has everything bundled.

---

## FAQ

**What Android versions work?**  
Any version that uses A/B format (Android 7.0+). Tested it on Android 10-16.

**Can I extract from full ROM zips?**  
Only if they have `payload.bin` inside. Fastboot images and other formats won't work.

**How long does it take?**  
Depends on the payload size. A typical 2-3GB File takes about 2-5 minutes on decent hardware.

**Will this work with my device's OTA?**  
If your device uses A/B updates, yes. Most modern devices do.
---

## Credits

Built by [himanshuksr0007](https://github.com/himanshuksr0007)

**Uses these libraries:**
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) - GUI
- [protobuf](https://github.com/protocolbuffers/protobuf) - Payload parsing
- [bsdiff4](https://github.com/ilanschnell/bsdiff4) - Binary diffs
- [brotli](https://github.com/google/brotli) - Brotli decompression
- [python-zstandard](https://github.com/indygreg/python-zstandard) - Zstandard decompression
- [fsspec](https://github.com/fsspec/filesystem_spec) - Remote file access

---

**Please Star this repo if you liked it**