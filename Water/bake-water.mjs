// Original equal-mass, weakly compressible SPH droplet solver. Node 20+, no dependencies.
import {writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const fps=24000/1001, frames=192, substeps=5, dt=1/(fps*substeps);
const spacing=.058, support=.146, densityRest=7.0;
const locations=[], velocities=[];
function seedDrop(center, radii, tilt, drift, circulation) {
  const spacingFCC = spacing/Math.SQRT2;
  const bound=Math.ceil(Math.max(...radii)/spacingFCC);
  for (let k=-bound;k<=bound;k++) for(let j=-bound;j<=bound;j++) for(let i=-bound;i<=bound;i++){
    if ((i+j+k)%2) continue;
    const x=i*spacingFCC, y=j*spacingFCC, z=k*spacingFCC;
    if ((x/radii[0])**2+(y/radii[1])**2+(z/radii[2])**2>1) continue;
    const rx=x*Math.cos(tilt)-y*Math.sin(tilt), ry=x*Math.sin(tilt)+y*Math.cos(tilt);
    locations.push([rx+center[0],ry+center[1],z+center[2]]);
    velocities.push([drift[0]-circulation*ry,drift[1]+circulation*rx,drift[2]+.18*circulation*ry]);
  }
}
seedDrop([-.038,-.014,.006],[.275,.183,.188],.64,[.014,-.012,0],.59);
seedDrop([.348,.167,.036],[.116,.096,.099],-.34,[-.132,-.038,-.009],-.62);
seedDrop([-.405,.223,-.05],[.078,.065,.066],.28,[.021,.012,.007],-.35);
seedDrop([.240,-.376,.048],[.073,.062,.061],.33,[.005,.008,-.008],.36);
seedDrop([-.468,.321,-.085],[.070,.060,.063],.64,[.003,.001,.006],.2);
seedDrop([.448,-.254,.105],[.064,.062,.050],-.2,[.004,-.001,.004],-.24);
const n=locations.length, positions=Float64Array.from(locations.flat()), velocity=Float64Array.from(velocities.flat());
const density=new Float64Array(n), pressure=new Float64Array(n), force=new Float64Array(n*3);
const pairI=new Uint16Array(n*n/2),pairJ=new Uint16Array(n*n/2);
const distance=new Float64Array(pairI.length), kernel=new Float64Array(pairI.length);

function step(t) {
  density.fill(0); force.fill(0);
  let pairs=0;
  for(let a=0;a<n;a++) for(let b=a+1;b<n;b++){
    const i=a*3,j=b*3, dx=positions[j]-positions[i],dy=positions[j+1]-positions[i+1],dz=positions[j+2]-positions[i+2];
    const d2=dx*dx+dy*dy+dz*dz;
    if(d2>=support*support) continue;
    const r=Math.sqrt(d2),q=1-r/support;
    pairI[pairs]=a; pairJ[pairs]=b; distance[pairs]=r; kernel[pairs++]=q;
    density[a]+=q*q; density[b]+=q*q;
  }
  for(let a=0;a<n;a++) pressure[a]=3.7*Math.max(0,density[a]-densityRest);
  for(let p=0;p<pairs;p++){
    const a=pairI[p],b=pairJ[p],i=a*3,j=b*3,r=distance[p],q=kernel[p];
    // Symmetric pressure and cohesion forces conserve linear momentum.
    const capillary=.25*4*q*(1-q);
    const core=10*Math.max(0,1-r/(spacing*1.06));
    const f=(capillary-.5*(pressure[a]+pressure[b])*q*q-core)/Math.max(1e-7,r);
    const visc=.34*q*q;
    for(let k=0;k<3;k++){
      const acc=f*(positions[j+k]-positions[i+k])+visc*(velocity[j+k]-velocity[i+k]);
      force[i+k]+=acc; force[j+k]-=acc;
    }
  }
  let meanX=0,meanY=0,meanZ=0;
  for(let a=0;a<n;a++){
    const i=3*a,x=positions[i],y=positions[i+1],z=positions[i+2];
    // An art-directed slowly turning, traceless tidal field excites capillary oscillations.
    const w=Math.exp(-(((x*x+y*y+z*z)/.074)**2));
    const ext=2.25*Math.sin(2.37*t+.39), shear=2.42*Math.cos(1.83*t+.5);
    force[i]+=w*(ext*x+shear*y+.44*z*Math.sin(t*1.92));
    force[i+1]+=w*(shear*x-ext*y+.32*z*Math.cos(2.51*t));
    force[i+2]+=w*(.44*x*Math.sin(1.92*t)+.32*y*Math.cos(2.51*t));
    meanX+=force[i]; meanY+=force[i+1]; meanZ+=force[i+2];
  }
  const mean=[meanX/n,meanY/n,meanZ/n];
  for(let i=0;i<positions.length;i++) {
    velocity[i]+=dt*(force[i]-mean[i%3]); positions[i]+=dt*velocity[i];
    if(!Number.isFinite(positions[i]) || Math.abs(positions[i])>.79) throw Error('Droplet outside reconstruction volume');
  }
}
const result=Buffer.alloc(20+frames*n*6);
result.write('WTR2'); result.writeUInt32LE(frames,4); result.writeUInt32LE(n,8);
result.writeUInt32LE(24000,12); result.writeUInt32LE(1001,16);
for(let f=0;f<frames;f++){
  for(let i=0;i<positions.length;i++)result.writeInt16LE(Math.round(positions[i]*32767),20+2*(f*n*3+i));
  if(f+1<frames)for(let s=0;s<substeps;s++)step((f*substeps+s)*dt);
}
writeFileSync(fileURLToPath(new URL('./water-particles.bin',import.meta.url)),result);
console.log(`Baked ${frames} frames, ${n} particles; ${substeps} substeps/frame; ${result.length} bytes.`);
