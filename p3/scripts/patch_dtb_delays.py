import struct, sys, os

def patch(path, vals):
    d = bytearray(open(path, 'rb').read())
    magic, ts, off_st, off_str, _, ver, _ = struct.unpack_from('>7I', d, 0)
    assert magic == 0xD00DFEED, 'bad magic'
    pos = off_st; stack = []; cur = None; found = {}
    while pos < len(d):
        tok = struct.unpack_from('>I', d, pos)[0]; pos += 4
        if tok == 1:
            e = d.index(b'\0', pos)
            stack.append(d[pos:e].decode())
            cur = '/' + '/'.join(x for x in stack if x)
            pos = (e + 1 + 3) & ~3
        elif tok == 2:
            stack.pop(); cur = '/' + '/'.join(x for x in stack if x)
            pos = (pos + 3) & ~3
        elif tok == 3:
            ln, noff = struct.unpack_from('>II', d, pos); pos += 8
            s = off_str + noff
            name = d[s:d.index(b'\0', s)].decode()
            if cur == '/ethernet@fe010000' and name in vals:
                old = struct.unpack_from('>I', d, pos)[0]
                struct.pack_into('>I', d, pos, vals[name])
                found[name] = (old, vals[name])
            pos = (pos + ln + 3) & ~3
        elif tok == 9:
            break
    if set(found) != set(vals):
        sys.exit('!! props not found: %s' % found)
    for k, (o, n) in found.items():
        print('%s  %s: 0x%x -> 0x%x' % (os.path.basename(path), k, o, n))
    open(path, 'wb').write(d)
    print('OK', path)

patch(sys.argv[1], {'tx_delay': 0x25, 'rx_delay': 0x15})
