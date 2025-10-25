#!/usr/bin/env python3
"""
OTA Payload Extractor
Pulls partition images out of Android OTA packages. Supports all the compression types
and handles differential updates if you have the original images lying around.
"""
import struct
import hashlib
import bz2
import sys
import argparse
import bsdiff4
import io
import os
import brotli
import zipfile
import zstandard
import fsspec
import urllib.parse
from pathlib import Path


try:
    import lzma
except ImportError:
    from backports import lzma

import update_metadata_pb2 as um


BSDF2_MAGIC = b'BSDF2'
# Flatten nested lists - just for fun, could've done this inline but whatever
flatten = lambda l: [item for sublist in l for item in sublist]


def u32(x):
    """Read 4-byte big-endian unsigned int"""
    return struct.unpack('>I', x)[0]


def u64(x):
    """Read 8-byte big-endian unsigned int"""
    return struct.unpack('>Q', x)[0]


def bsdf2_decompress(alg, data):
    """Decompress data based on algorithm ID"""
    if alg == 0:
        # No compression, just return as-is
        return data
    elif alg == 1:
        # BZ2
        return bz2.decompress(data)
    elif alg == 2:
        # Brotli
        return brotli.decompress(data)


def bsdf2_read_patch(fi):
    """Parse bsdiff/BSDF2 patch header and sections"""
    magic = fi.read(8)
    
    # Check if it's old bsdiff4 format or new BSDF2
    if magic == bsdiff4.format.MAGIC:
        # Legacy bsdiff4 always uses bzip2
        alg_control = alg_diff = alg_extra = 1
    elif magic[:5] == BSDF2_MAGIC:
        # Grab compression algorithms from header bytes
        alg_control = magic[5]
        alg_diff = magic[6]
        alg_extra = magic[7]
    else:
        raise ValueError("incorrect magic bsdiff/BSDF2 header")

    # Read section sizes
    len_control = bsdiff4.core.decode_int64(fi.read(8))
    len_diff = bsdiff4.core.decode_int64(fi.read(8))
    len_dst = bsdiff4.core.decode_int64(fi.read(8))

    # Decompress control block and parse it
    bcontrol = bsdf2_decompress(alg_control, fi.read(len_control))
    tcontrol = [(bsdiff4.core.decode_int64(bcontrol[i:i + 8]),
                 bsdiff4.core.decode_int64(bcontrol[i + 8:i + 16]),
                 bsdiff4.core.decode_int64(bcontrol[i + 16:i + 24]))
                for i in range(0, len(bcontrol), 24)]

    # Decompress diff and extra sections
    bdiff = bsdf2_decompress(alg_diff, fi.read(len_diff))
    bextra = bsdf2_decompress(alg_extra, fi.read())
    
    return len_dst, tcontrol, bdiff, bextra


def verify_contiguous(exts):
    """Check if extents form a contiguous block sequence (probably not used much)"""
    blocks = 0
    for ext in exts:
        if ext.start_block != blocks:
            return False
        blocks += ext.num_blocks
    return True


def open_payload_file(file_path):
    """Open payload file from local path or URL, handle ZIP if needed"""
    is_url = file_path.startswith(('http://', 'https://', 's3://', 'gs://'))
    
    if is_url:
        # Remote file - use fsspec to handle different protocols
        protocol = urllib.parse.urlparse(file_path).scheme
        fs = fsspec.filesystem(protocol)
        remote_file = fs.open(file_path)
        
        if zipfile.is_zipfile(remote_file):
            remote_file.seek(0)
            with zipfile.ZipFile(remote_file) as zf:
                if "payload.bin" in zf.namelist():
                    return zf.open("payload.bin")
                else:
                    raise ValueError("payload.bin not found in zip file")
        else:
            # Direct payload file
            return remote_file
    else:
        # Local file
        if zipfile.is_zipfile(file_path):
            with zipfile.ZipFile(file_path) as zf:
                if "payload.bin" in zf.namelist():
                    return zf.open("payload.bin")
                else:
                    raise ValueError("payload.bin not found in zip file")
        else:
            # Just a regular payload.bin file
            return open(file_path, 'rb')


def data_for_op(op, payload_file, out_file, old_file, data_offset, block_size, log_callback=None):
    """Apply a single operation - the actual extraction logic"""
    # Read the raw compressed/raw data for this operation
    payload_file.seek(data_offset + op.data_offset)
    raw_data = payload_file.read(op.data_length)

    if log_callback:
        log_callback(f"  [OP] Type: {op.type}, Data offset: {op.data_offset}, Data length: {op.data_length}")

    # Verify data integrity if hash is present
    if op.data_sha256_hash:
        calculated_hash = hashlib.sha256(raw_data).digest()
        if calculated_hash != op.data_sha256_hash:
            msg = f'Operation data hash mismatch!'
            if log_callback: 
                log_callback(msg)
            raise ValueError(msg)
        else:
            if log_callback: 
                log_callback("  [OP] SHA256 hash OK")

    try:
        # Type 0: REPLACE - just write raw data as-is
        if op.type == 0:  # REPLACE
            if log_callback: 
                log_callback(f"  [OP] REPLACE: Writing raw data: {len(raw_data)} bytes")
            out_file.seek(op.dst_extents[0].start_block * block_size)
            out_file.write(raw_data)
        
        # Type 1: REPLACE_BZ - bzip2 compressed
        elif op.type == 1:
            if log_callback: 
                log_callback(f"  [OP] REPLACE_BZ: Decompressing with BZ2: input {len(raw_data)} bytes")
            dec = bz2.BZ2Decompressor()
            data = dec.decompress(raw_data)
            if log_callback: 
                log_callback(f"  [OP] BZ2 decompressed size: {len(data)} bytes")
            out_file.seek(op.dst_extents[0].start_block * block_size)
            out_file.write(data)
        
        # Type 3 & 8: REPLACE_XZ - LZMA/XZ compressed
        elif op.type == 3 or op.type == 8:  # REPLACE_XZ
            if log_callback: 
                log_callback(f"  [OP] REPLACE_XZ: Decompressing with XZ: input {len(raw_data)} bytes")
            dec = lzma.LZMADecompressor()
            data = dec.decompress(raw_data)
            if log_callback: 
                log_callback(f"  [OP] XZ decompressed size: {len(data)} bytes")
            out_file.seek(op.dst_extents[0].start_block * block_size)
            out_file.write(data)
        
        # Type 4: REPLACE_ZSTD - Zstandard compressed
        elif op.type == 4:  # ZSTD
            if log_callback: 
                log_callback(f"  [OP] ZSTD: Decompressing with ZSTD: input {len(raw_data)} bytes")
            dec = zstandard.ZstdDecompressor().decompressobj()
            data = dec.decompress(raw_data)
            if log_callback: 
                log_callback(f"  [OP] ZSTD decompressed size: {len(data)} bytes")
            out_file.seek(op.dst_extents[0].start_block * block_size)
            out_file.write(data)
        
        # Type 5: SOURCE_COPY - just copy from original image (for differential updates)
        elif op.type == 5:
            if not old_file:
                msg = "[OP] SOURCE_COPY requires old_file!"
                if log_callback: 
                    log_callback(msg)
                raise ValueError(msg)
            if log_callback: 
                log_callback("[OP] SOURCE_COPY: Copying from original image")
            out_file.seek(op.dst_extents[0].start_block * block_size)
            for ext in op.src_extents:
                old_file.seek(ext.start_block * block_size)
                data = old_file.read(ext.num_blocks * block_size)
                out_file.write(data)
        
        # Type 6 & 10: SOURCE_BSDIFF - differential patch
        elif op.type == 6 or op.type == 10:  # SOURCE_BSDIFF or BROTLI_BSDIFF
            if not old_file:
                msg = "[OP] BSDIFF requires old_file!"
                if log_callback: 
                    log_callback(msg)
                raise ValueError(msg)
            if log_callback: 
                log_callback("[OP] BSDIFF: Applying patch")
            
            # Gather all source data
            out_file.seek(op.dst_extents[0].start_block * block_size)
            tmp_buff = io.BytesIO()
            for ext in op.src_extents:
                old_file.seek(ext.start_block * block_size)
                old_data = old_file.read(ext.num_blocks * block_size)
                tmp_buff.write(old_data)
            
            # Apply the patch
            tmp_buff.seek(0)
            old_data = tmp_buff.read()
            tmp_buff.seek(0)
            tmp_buff.write(bsdiff4.core.patch(old_data, *bsdf2_read_patch(io.BytesIO(raw_data))))
            
            # Write patched data to output
            n = 0
            tmp_buff.seek(0)
            for ext in op.dst_extents:
                tmp_buff.seek(n * block_size)
                n += ext.num_blocks
                data = tmp_buff.read(ext.num_blocks * block_size)
                out_file.seek(ext.start_block * block_size)
                out_file.write(data)
        
        # Type 2: ZERO - write a bunch of zeros
        elif op.type == 2:
            total_bytes = sum(ext.num_blocks * block_size for ext in op.dst_extents)
            if log_callback: 
                log_callback(f"  [OP] ZERO: Writing {total_bytes} bytes of zeros")
            for ext in op.dst_extents:
                out_file.seek(ext.start_block * block_size)
                out_file.write(b'\x00' * ext.num_blocks * block_size)
        
        else:
            # Unknown operation type
            msg = f"[OP] Unsupported operation type: {op.type}"
            if log_callback: 
                log_callback(msg)
            raise ValueError(msg)
            
    except Exception as e:
        msg = f"Exception during operation: {str(e)} [type: {op.type}, data_offset: {op.data_offset}]"
        if log_callback: 
            log_callback(msg)
        raise


def dump_part(part, payload_file, data_offset, block_size, out_dir, old_dir=None, use_diff=False, log_callback=None):
    """Extract a single partition by processing all its operations"""
    msg = f"Processing {part.partition_name} partition"
    if log_callback: 
        log_callback(msg)
    
    Path(out_dir).mkdir(exist_ok=True)

    # Open output file for this partition
    out_file = open(f'{out_dir}/{part.partition_name}.img', 'wb')

    # Handle differential OTA - need the old partition image
    old_file = None
    if use_diff:
        old_file_path = f'{old_dir}/{part.partition_name}.img'
        if os.path.exists(old_file_path):
            old_file = open(old_file_path, 'rb')
        else:
            msg = f"Warning: Original image {old_file_path} not found for differential OTA"
            if log_callback: 
                log_callback(msg)
            old_file = None

    # Process each operation for this partition
    for op in part.operations:
        data_for_op(op, payload_file, out_file, old_file, data_offset, block_size, log_callback)
        if log_callback: 
            log_callback(f"  Operation {op.type} completed.")

    # Clean up
    out_file.close()
    if old_file:
        old_file.close()
    
    msg = f"{part.partition_name} extraction done"
    if log_callback: 
        log_callback(msg)


def run_payload_dumper(payload_path, out_dir="output", diff=False, old_dir="old", images=None, log_callback=None, progress_callback=None, cancel_flag=None):
    """Main extraction logic - reads payload header and processes partitions"""
    if log_callback: 
        log_callback("Opening payload file...")
    
    with open_payload_file(payload_path) as payload_file:
        # Verify magic header
        magic = payload_file.read(4)
        if magic != b'CrAU':
            msg = "Invalid magic header, not an OTA payload"
            if log_callback: 
                log_callback(msg)
            raise ValueError(msg)
        
        # Check format version
        file_format_version = u64(payload_file.read(8))
        if file_format_version != 2:
            msg = f"Unsupported file format version: {file_format_version}"
            if log_callback: 
                log_callback(msg)
            raise ValueError(msg)
        
        # Read manifest
        manifest_size = u64(payload_file.read(8))
        metadata_signature_size = 0
        if file_format_version > 1:
            metadata_signature_size = u32(payload_file.read(4))
        
        manifest = payload_file.read(manifest_size)
        metadata_signature = payload_file.read(metadata_signature_size)
        
        # Everything after the manifest/metadata is partition data
        data_offset = payload_file.tell()
        
        # Parse the manifest
        dam = um.DeltaArchiveManifest()
        dam.ParseFromString(manifest)
        block_size = dam.block_size

        # Figure out which partitions to extract
        parts_to_dump = dam.partitions if not images else [
            part for part in dam.partitions if part.partition_name in (images if images else [])
        ]
        
        total = len(parts_to_dump)
        for idx, part in enumerate(parts_to_dump):
            # Check if extraction was cancelled
            if cancel_flag and cancel_flag():
                if log_callback: 
                    log_callback("Extraction cancelled.")
                break
            
            dump_part(
                part, payload_file, data_offset, block_size, out_dir,
                old_dir if diff else None, diff, log_callback
            )
            
            # Report progress
            percent = int((idx + 1) / total * 100)
            if progress_callback:
                progress_callback(percent)
    
    if log_callback: 
        log_callback("All done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='OTA payload dumper')
    parser.add_argument('payload_path', type=str,
                        help='payload file path or URL (can be a zip file)')
    parser.add_argument('--out', default='output',
                        help='output directory (default: output)')
    parser.add_argument('--diff', action='store_true',
                        help='extract differential OTA, put original images in old dir')
    parser.add_argument('--old', default='old',
                        help='directory with original images for differential OTA (default: old)')
    parser.add_argument('--images', default="",
                        help='comma-separated list of images to extract (default: all)')
    args = parser.parse_args()
    
    images = args.images.split(",") if args.images else None
    
    try:
        run_payload_dumper(args.payload_path, args.out, args.diff, args.old, images)
    except Exception as e:
        print("Error:", e)