import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
// Source-owned, execution-free PE64 DLL: answer()=42 and add(a,b)=a+b.
const out=path.join(import.meta.dirname,'fixtures','jarvis-owned.dll');
const b=Buffer.alloc(0x600); const u16=(o,v)=>b.writeUInt16LE(v,o),u32=(o,v)=>b.writeUInt32LE(v,o),str=(o,s)=>b.write(s+'\0',o,'ascii');
u16(0,0x5a4d);u32(0x3c,0x80);u32(0x80,0x4550);
u16(0x84,0x8664);u16(0x86,2);u16(0x94,0xf0);u16(0x96,0x2022);
const p=0x98;u16(p,0x20b);b[p+2]=14;u32(p+4,0x200);u32(p+8,0x200);u32(p+16,0);u32(p+20,0x1000);
b.writeBigUInt64LE(0x180000000n,p+24);u32(p+32,0x1000);u32(p+36,0x200);u16(p+40,6);u16(p+48,6);u32(p+56,0x3000);u32(p+60,0x200);u16(p+68,3);u16(p+70,0x140);
for(const [o,v] of [[72,0x100000n],[80,0x1000n],[88,0x100000n],[96,0x1000n]])b.writeBigUInt64LE(v,p+o);
u32(p+108,16);u32(p+112,0x2000);u32(p+116,0x100);
function section(o,name,rva,ptr,flags){str(o,name);u32(o+8,0x200);u32(o+12,rva);u32(o+16,0x200);u32(o+20,ptr);u32(o+36,flags);}
section(0x188,'.text',0x1000,0x200,0x60000020);section(0x1b0,'.rdata',0x2000,0x400,0x40000040);
b.set([0xb8,42,0,0,0,0xc3],0x200);b.set([0x8d,0x04,0x11,0xc3],0x210);
const e=0x400;u32(e+12,0x2070);u32(e+16,1);u32(e+20,2);u32(e+24,2);u32(e+28,0x2028);u32(e+32,0x2030);u32(e+36,0x2038);
u32(e+40,0x1010);u32(e+44,0x1000);u32(e+48,0x2080);u32(e+52,0x2090);u16(e+56,0);u16(e+58,1);
str(e+0x70,'jarvis-owned.dll');str(e+0x80,'jarvis_add');str(e+0x90,'jarvis_answer');str(e+0xa0,'JARVIS owned static analysis fixture');
await fs.mkdir(path.dirname(out),{recursive:true});await fs.writeFile(out,b);
console.log(JSON.stringify({path:out,sha256:crypto.createHash('sha256').update(b).digest('hex'),bytes:b.length,target_executed:false,owned:true},null,2));
