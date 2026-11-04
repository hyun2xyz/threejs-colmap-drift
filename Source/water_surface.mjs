import * as T from 'three';
import {MarchingCubes} from 'three/addons/objects/MarchingCubes.js';
import {createWater} from '../Water/water.mjs';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const dir=path.dirname(fileURLToPath(import.meta.url));const out=path.resolve(process.argv[2] || 'water-cache/surface');
await mkdir(out,{recursive:true});
const binary=await readFile(path.join(dir,'../Water/water-particles.bin'));
globalThis.fetch=async ()=>new Response(binary);
const water=await createWater(T,MarchingCubes);
for(let i=0;i<192;i++){
 water.update(i*1001/24000);const g=water.mesh.geometry,n=g.drawRange.count;
 const xyz=g.attributes.position.array,norm=g.attributes.normal.array,buf=new Float32Array(n*6);
 for(let v=0;v<n;v++)for(let c=0;c<3;c++){buf[v*6+c]=xyz[v*3+c]*water.mesh.scale.x;buf[v*6+3+c]=norm[v*3+c];}
 await writeFile(path.join(out,String(i).padStart(3,'0')+'.bin'),Buffer.from(buf.buffer));
}
console.log('192 marching-cubes surfaces');
