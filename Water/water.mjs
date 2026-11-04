/** Reconstruct the full 192-frame zero-gravity fluid simulation for Three.js r180. */
export async function createWater(THREE, MarchingCubes, options = {}) {
  const response = await fetch(options.url || new URL('./water-particles.bin', import.meta.url));
  if (!response.ok) throw Error(`Failed to fetch water cache (HTTP ${response.status})`);
  const data = await response.arrayBuffer(), header = new DataView(data);
  if (header.getUint32(0) !== 0x57545232) throw Error('Invalid water cache signature');
  const frames = header.getUint32(4,true), particles = header.getUint32(8,true);
  const fps = header.getUint32(12,true) / header.getUint32(16,true);
  if(data.byteLength!==20 + 6*frames*particles) throw Error('Truncated water cache');
  const values = new Int16Array(data,20);
  const material = new THREE.MeshPhysicalMaterial({
    name:'Water • IOR 1.333', color:0xffffff, metalness:0, roughness:.032,
    transmission:1, thickness:.48, ior:1.333, envMapIntensity:1.08,
    attenuationColor:0xc8efec, attenuationDistance:4.0,
    specularIntensity:1, specularColor:0xffffff
  });
  const size = options.resolution || 56, halfExtent = .76;
  const mesh = new MarchingCubes(size,material,false,false,22000);
  mesh.name='Free surface • compact particle-density isosurface';
  mesh.scale.setScalar(halfExtent);
  mesh.isolation = 2.95;
  const object = new THREE.Group();
  object.name = 'Weightless water';
  object.add(mesh);
  const gridScale=size/(2*halfExtent), gridRadius=.127*gridScale, r2=gridRadius*gridRadius;
  const gridCenter=size/2, size2=size*size, coords=new Float64Array(particles*3);
  let lastTime=-1;
  function update(seconds) {
    const sample=Math.min(frames-1,Math.max(0,seconds*fps));
    if(sample===lastTime)return;
    lastTime=sample;
    const i0=Math.floor(sample), i1=Math.min(frames-1,i0+1), mix=sample-i0;
    const a=i0*coords.length,b=i1*coords.length;
    for(let i=0;i<coords.length;i++)
      coords[i]=gridCenter+gridScale*(values[a+i]+mix*(values[b+i]-values[a+i]))/32767;
    mesh.field.fill(0);
    mesh.normal_cache.fill(0);
    for(let i=0;i<coords.length;i+=3) {
      const cx=coords[i],cy=coords[i+1],cz=coords[i+2];
      const minX=Math.max(1,Math.ceil(cx-gridRadius)),maxX=Math.min(size-2,Math.floor(cx+gridRadius));
      const minY=Math.max(1,Math.ceil(cy-gridRadius)),maxY=Math.min(size-2,Math.floor(cy+gridRadius));
      const minZ=Math.max(1,Math.ceil(cz-gridRadius)),maxZ=Math.min(size-2,Math.floor(cz+gridRadius));
      for(let z=minZ;z<=maxZ;z++) {
        const dz2=(z-cz)**2;
        for(let y=minY;y<=maxY;y++) {
          const yz2=(y-cy)**2+dz2, base=size2*z+size*y;
          if(yz2>=r2)continue;
          for(let x=minX;x<=maxX;x++){
            const u=1-((x-cx)**2+yz2)/r2;
            if(u>0)mesh.field[base+x]+=u*u*u;
          }
        }
      }
    }
    mesh.update();
  }
  update(0);
  return {object, mesh, material, update, frames, fps, particles,
    dispose(){mesh.geometry.dispose();material.dispose();}};
}
