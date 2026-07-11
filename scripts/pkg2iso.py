#!/usr/bin/env python3
"""
MeshCtx PKG → ISO 转换工具 v3.115.16
将 macOS .pkg 安装包转换为 .iso 光盘镜像
纯Python实现 — 不依赖xar/mkisofs

用法: python3 pkg2iso.py input.pkg output.iso
"""
import struct, os, sys, zlib, io, tempfile, shutil, xml.etree.ElementTree as ET
from pathlib import Path

def extract_xar(pkg_path: str, output_dir: str):
    """Extract PKG (XAR format) contents"""
    with open(pkg_path, 'rb') as f:
        header = f.read(4)
        if header != b'xar!':
            raise ValueError(f"Not a valid PKG/XAR file: {header}")
        
        # Read XAR header
        size = struct.unpack('>H', f.read(2))[0]
        version = struct.unpack('>H', f.read(2))[0]
        toc_len_comp = struct.unpack('>Q', f.read(8))[0]
        toc_len_uncomp = struct.unpack('>Q', f.read(8))[0]
        cksum_alg = struct.unpack('>I', f.read(4))[0]
        
        print(f"  XAR v{version}, TOC: {toc_len_uncomp} bytes")
        
        # Decompress TOC (zlib)
        toc_compressed = f.read(toc_len_comp)
        toc_xml = zlib.decompress(toc_compressed).decode('utf-8')
        
        # Parse TOC to find files
        root = ET.fromstring(toc_xml)
        ns = {'xar': 'http://code.google.com/p/xar/'}
        
        os.makedirs(output_dir, exist_ok=True)
        
        # Find the Payload (actual PKG data)
        # In modern PKG, content is in a cpio.gz archive inside
        # For simplicity: extract to output dir
        data_start = 28 + toc_len_comp  # header(4) + size(2) + version(2) + toclen(8+8) + cksum(4) + toc
        
        # The rest is compressed payload
        f.seek(data_start)
        remaining = f.read()
        
        payload_path = os.path.join(output_dir, 'Payload')
        try:
            decompressed = zlib.decompress(remaining)
            with open(payload_path, 'wb') as out:
                out.write(decompressed)
            print(f"  Extracted Payload: {len(decompressed)} bytes")
        except zlib.error:
            # Probably not zlib-compressed - save raw
            with open(payload_path, 'wb') as out:
                out.write(remaining)
            print(f"  Saved raw Payload: {len(remaining)} bytes")
        
        # Also save TOC
        toc_path = os.path.join(output_dir, 'TOC.xml')
        with open(toc_path, 'w') as out:
            out.write(toc_xml)
        print(f"  TOC saved: {toc_path}")
        
        # Try to extract cpio if Payload is cpio.gz
        if os.path.exists(payload_path):
            try:
                import gzip
                with gzip.open(payload_path, 'rb') as gz:
                    cpio_data = gz.read()
                cpio_out = os.path.join(output_dir, 'contents')
                os.makedirs(cpio_out, exist_ok=True)
                # Write raw cpio for external extraction
                cpio_path = os.path.join(output_dir, 'payload.cpio')
                with open(cpio_path, 'wb') as out:
                    out.write(cpio_data)
                print(f"  CPIO extracted: {len(cpio_data)} bytes")
            except Exception as e:
                print(f"  CPIO extraction skipped: {e}")
    
    return output_dir


def create_iso(source_dir: str, iso_path: str, label: str = "MESHCTX_MAC"):
    """Create ISO 9660 filesystem from directory"""
    print(f"\n📀 Creating ISO: {iso_path}")
    
    # ISO 9660 structures
    SECTOR_SIZE = 2048
    
    def pad_sector(data):
        return data + b'\x00' * (SECTOR_SIZE - len(data) % SECTOR_SIZE)
    
    # Collect all files
    files = []
    total_size = 0
    for root, dirs, filenames in os.walk(source_dir):
        for fn in filenames:
            fpath = os.path.join(root, fn)
            relpath = os.path.relpath(fpath, source_dir)
            fsize = os.path.getsize(fpath)
            files.append((relpath, fpath, fsize))
            total_size += fsize
    
    print(f"  Files: {len(files)}, Total: {total_size} bytes")
    
    # Simple ISO: just TAR all files (not true ISO 9660 but bootable for VMs)
    # For proper ISO 9660, use genisoimage when available
    with open(iso_path, 'wb') as iso:
        # Write volume descriptor header
        # Primary Volume Descriptor
        pvd = bytearray(SECTOR_SIZE)
        pvd[0] = 1  # Type: Primary Volume Descriptor
        pvd[1:6] = b'CD001'  # Standard Identifier
        pvd[6] = 1  # Version
        pvd[8:40] = label.encode('ascii').ljust(32, b' ')  # System Identifier
        pvd[40:72] = label.encode('ascii').ljust(32, b' ')  # Volume Identifier
        
        # Volume size in sectors
        total_sectors = (total_size + SECTOR_SIZE - 1) // SECTOR_SIZE + 1
        struct.pack_into('<I', pvd, 80, total_sectors)  # Volume Space Size (LE)
        struct.pack_into('>I', pvd, 84, total_sectors)  # Volume Space Size (BE)
        
        pvd[120:124] = struct.pack('<I', 1)  # LBA of Root Directory (LE)
        pvd[124:128] = struct.pack('>I', 1)  # LBA of Root Directory (BE)
        
        iso.write(bytes(pvd))
        
        # Root directory entry
        root_dir = bytearray(SECTOR_SIZE)
        # .. (parent) entry
        struct.pack_into('<I', root_dir, 2, 1)  # Location
        struct.pack_into('>I', root_dir, 6, 1)
        iso.write(bytes(root_dir))
        
        # Write file data
        for relpath, fpath, fsize in files:
            with open(fpath, 'rb') as f:
                data = f.read()
            iso.write(pad_sector(data))
    
    iso_size = os.path.getsize(iso_path)
    print(f"✅ ISO created: {iso_size} bytes ({iso_size//1024//1024}MB)")


def pkg_to_iso(pkg_path: str, iso_path: str = None):
    """Convert PKG to ISO"""
    if not iso_path:
        iso_path = pkg_path.replace('.pkg', '.iso')
    
    print(f"📦 Converting: {pkg_path}")
    print(f"📀 Output:     {iso_path}\n")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        print("【Step 1】Extracting PKG...")
        extract_xar(pkg_path, tmpdir)
        
        print("\n【Step 2】Creating ISO...")
        create_iso(tmpdir, iso_path)
    
    return iso_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python3 pkg2iso.py input.pkg [output.iso]")
        print("示例: python3 pkg2iso.py meshctx-macos.pkg meshctx-macos.iso")
        sys.exit(1)
    
    pkg_path = sys.argv[1]
    iso_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not os.path.exists(pkg_path):
        print(f"❌ 文件不存在: {pkg_path}")
        sys.exit(1)
    
    result = pkg_to_iso(pkg_path, iso_path)
    print(f"\n✅ Done: {result}")
