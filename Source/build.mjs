/** Rebuild with Node 22+ via npm install && npm run build in this directory.
 * Optional argument: output directory for the individual GLBs. All art and geometry are procedural.
 * Local axes are Y up, Z toward the main viewing camera; group pivot is centered.
 */
import * as THREE from 'three';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { createCanvas, Canvas } from '@napi-rs/canvas';
import { validateBytes } from 'gltf-validator';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// The exporter normally uses the browser for PNG encoding and reading its GLB blob.
globalThis.HTMLCanvasElement = Canvas;
globalThis.document = { createElement: () => createCanvas(1, 1) };
globalThis.FileReader = class {
  async readAsArrayBuffer(blob) {
    this.result = await blob.arrayBuffer();
    this.onloadend?.();
  }
};
const tau = Math.PI * 2;
let seed = 411301;
function random() {
  seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
  return seed / 4294967296;
}
function paint(w, h, color, jitter) {
  const canvas = createCanvas(w, h);
  const c = canvas.getContext('2d');
  const pixels = c.createImageData(w, h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y*w+x)*4;
      const delta = (random() - .5)*jitter;
      for (let k = 0; k < 3; k++) pixels.data[i+k] = color[k] + delta;
      pixels.data[i+3] = 255;
    }
  }
  c.putImageData(pixels, 0, 0);
  return canvas;
}
function texture(canvas, name, color = true) {
  // Hide the native raw-data method so the exporter identifies this as a canvas.
  Object.defineProperty(canvas, 'data', {value: undefined});
  const result = new THREE.CanvasTexture(canvas);
  result.name = name;
  if (color) result.colorSpace = THREE.SRGBColorSpace;
  result.wrapS = THREE.RepeatWrapping;
  return result;
}
function type(c, label, x, y, font, color) {
  c.fillStyle = color;
  c.font = font;
  c.textAlign = 'center';
  c.textBaseline = 'middle';
  c.fillText(label, x, y);
}
function ringLine(c, y, color, height = 1) {
  c.fillStyle = color;
  c.fillRect(0, y, c.canvas.width, height);
}
function enamel() {
  const art = paint(1536, 1024, [80,115,107], 6);
  const c = art.getContext('2d');
  const ink = '#f0e6c7';
  for (let i=0;i<340;i++) {
    const x=random()*1536, y=random()*1024;
    c.fillStyle = i%2 ? 'rgba(40,55,51,.12)' : 'rgba(213,210,169,.14)';
    c.fillRect(x,y,random()*1.9+.35,random()*1.2+.4);
  }
  // Screen print sinks into the baked enamel. The seam falls at the back.
  c.strokeStyle = ink; c.lineWidth = 3.1; c.lineJoin = 'round';
  c.beginPath(); c.moveTo(731,411); c.lineTo(752,378); c.lineTo(765,396);
  c.lineTo(780,369); c.lineTo(808,411); c.closePath(); c.stroke();
  c.beginPath();c.moveTo(767,395);c.lineTo(778,387);c.lineTo(785,392);c.stroke();
  type(c,'FIELD',768,461,'bold 68px Arial',ink);
  type(c,'S U P P L Y',768,510,'bold 25px Arial',ink);
  c.fillStyle=ink;c.fillRect(703,540,130,2);
  type(c,'Nº 02   /   500 ML',768,568,'bold 16px Arial',ink);
  type(c,'VACUUM INSULATED',768,861,'bold 12px Arial',ink);
  return texture(art,'Fired enamel · screen print');
}
function pottery() {
  const art = paint(1024, 512, [222,211,188], 7);
  const c = art.getContext('2d');
  for (let i=0;i<7200;i++) {
    const r=.23+random()**2*1.75;
    const x=random()*1024, y=random()*512;
    c.fillStyle=`rgba(91,65,45,${.07+random()*.43})`;
    c.beginPath();c.ellipse(x,y,r*.7,r,random()*3,0,tau);c.fill();
  }
  // Fine iron slip rings under the glaze.
  ringLine(c,39,'#887457',2);ringLine(c,47,'#635b4b',4);
  return texture(art,'Stoneware · iron flecks & slip bands');
}
function microNormal(name, amount) {
  const canvas = createCanvas(192,192), c=canvas.getContext('2d');
  const data = c.createImageData(192,192);
  for(let i=0;i<data.data.length;i+=4){
    data.data[i]=128+(random()-.5)*amount;
    data.data[i+1]=128+(random()-.5)*amount;
    data.data[i+2]=255;data.data[i+3]=255;
  }
  c.putImageData(data,0,0);
  return texture(canvas,name,false);
}
function label() {
  const art=paint(256,320,[167,73,46],9), c=art.getContext('2d');
  c.strokeStyle='#e5c199';c.lineWidth=2;c.strokeRect(13,13,230,294);
  type(c,'04',128,156,'bold 102px Georgia','#f4dbac');
  type(c,'C E Y L O N',128,234,'bold 19px Arial','#ffdfb4');
  type(c,'BLACK TEA',128,268,'13px Arial','#f9d9ae');
  c.fillStyle='#dfbb93';c.fillRect(99,74,58,2);
  return texture(art,'Letterpress · tea ticket');
}
function steelBrush() {
  const art=paint(256,320,[210,209,200],2), c=art.getContext('2d');
  for(let i=0;i<550;i++){
    const y=random()*320;c.strokeStyle=`rgba(101,99,96,${random()*.12})`;
    c.lineWidth=.4+random()*.65;c.beginPath();c.moveTo(0,y);c.lineTo(256,y);c.stroke();
  }
  return texture(art,'Lathe-brushed steel');
}
function material(name, color, roughness, metalness = 0, extras = {}) {
  const m = new THREE.MeshStandardMaterial({color,roughness,metalness,...extras});
  m.name = name;return m;
}
const textureEnamel=enamel(), textureClay=pottery(), ticketArt=label(), steelArt=steelBrush();
const bodyMat=material('01 · Field green / satin powder coat',0xffffff,.35,.16,{map:textureEnamel,normalMap:microNormal('Enamel grain',13)});
const green=material('02 · Enamel / rim & mount',0x537369,.33,.2);
const metal=material('03 · Brushed 304 steel',0xffffff,.28,.91,{map:steelArt});
const polished=material('04 · Polished edge',0xdfddd0,.24,.92);
const rubber=material('05 · Charcoal elastomer',0x2c322d,.76);
const dark=material('06 · Molded dark olive resin',0x37423a,.43,.04);
const cupWall=material('07 · Oatmeal glaze / iron fleck',0xffffff,.31,.015,{map:textureClay,normalMap:microNormal('Glaze grain',9)});
const cupInner=material('08 · Cream interior glaze',0xe5dac4,.245);
const clay=material('09 · Unglazed clay footing',0xb79973,.79);
const handleClay=material('10 · Glazed ceramic handle',0xdaceb8,.31);
const infusion=material('11 · Strong amber tea',0x66321b,.17,.06);
const meniscus=material('12 · Infusion edge / amber',0x844825,.18,.04);
const thread=material('13 · Cotton tea twine',0xdecca7,.84);
const paper=material('14 · Printed vermilion paper',0xffffff,.83,0,{map:ticketArt,side:THREE.DoubleSide});
const gold=material('15 · Brass hardware',0xb89d65,.3,.78);

const scene = new THREE.Scene();
function group(parent,name) { const g=new THREE.Group(); g.name=name;parent.add(g);return g; }
function mesh(parent,name,geometry,mat) {
  if(!mat.map && !mat.normalMap) geometry.deleteAttribute('uv');
  const obj=new THREE.Mesh(geometry,mat);obj.name=name;parent.add(obj);return obj;
}
const assembly=group(scene,'Everyday • Field tea set');
const flask=group(assembly,'01 / Vacuum flask');
const cup=group(assembly,'02 / Stoneware tea mug');
const sachet=group(cup,'03 / Paper tea tag');
function turned(parent,name,profile,mat,segments=80,flutes=0) {
  const geo = new THREE.LatheGeometry(profile.map(([r,y])=>new THREE.Vector2(r,y)),segments,-Math.PI);
  const positions=geo.attributes.position, uv=geo.attributes.uv;
  const ys=profile.map(p=>p[1]),lo=Math.min(...ys),hi=Math.max(...ys);
  for(let i=0;i<positions.count;i++) {
    const k=i%profile.length,u=Math.floor(i/profile.length)/segments;
    uv.setXY(i,u,(profile[k][1]-lo)/(hi-lo || 1));
    if(flutes){
      const weight=Math.sin(Math.PI*k/(profile.length-1))**.8;
      const gain=1-.020*weight*(.5+.5*Math.cos(tau*flutes*u))**2;
      positions.setX(i,positions.getX(i)*gain);positions.setZ(i,positions.getZ(i)*gain);
    }
  }
  if(mat.normalMap) {
    const tangents=[];
    for(let i=0;i<positions.count;i++) {
      const phi=-Math.PI+tau*Math.floor(i/profile.length)/segments;
      tangents.push(Math.cos(phi),0,-Math.sin(phi),1);
    }
    geo.setAttribute('tangent',new THREE.Float32BufferAttribute(tangents,4));
  }
  if(flutes)geo.computeVertexNormals();
  geo.normalizeNormals();
  return mesh(parent,name,geo,mat);
}
function torus(parent,name,r,t,y,mat) {
  const g=mesh(parent,name,new THREE.TorusGeometry(r,t,10,96),mat);
  g.rotation.x=-Math.PI/2;g.position.y=y;return g;
}
function tube(parent,name,points,r,mat,long=42,around=12) {
  const path=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)));
  return mesh(parent,name,new THREE.TubeGeometry(path,long,r,around,false),mat);
}
function ellipsoid(parent,name,p,size,mat) {
  const o=mesh(parent,name,new THREE.SphereGeometry(1,32,20),mat);
  o.position.set(...p);o.scale.set(...size);return o;
}
function rounded(parent,name,p,size,r,mat) {
  const o=mesh(parent,name,new RoundedBoxGeometry(...size,3,r),mat);
  o.position.set(...p);return o;
}
// Separate manufacturing parts preserve editable material boundaries after import.
turned(flask,'Spun enamel barrel',[[.001,.086],[.27,.086],[.292,.092],[.305,.11],[.311,.145],[.312,.21],[.311,1.046],[.308,1.089],[.30,1.12],[.28,1.153],[.235,1.188],[.214,1.202],[.21,1.212],[.211,1.232]],bodyMat,112);
turned(flask,'Rolled bumper / stainless',[[.001,.035],[.252,.035],[.288,.042],[.304,.053],[.316,.073],[.318,.099],[.315,.132],[.309,.14]],metal,96);
torus(flask,'Bumper top bead',.312,.0045,.133,polished);
turned(flask,'Inset shock foot',[[.001,.028],[.245,.028],[.264,.033],[.269,.046],[.265,.055]],rubber);
turned(flask,'Neck ring',[[.203,1.191],[.219,1.198],[.222,1.221],[.217,1.259],[.212,1.265]],metal);
torus(flask,'Neck seal',.218,.008,1.246,rubber);
turned(flask,'Cup cap / steel wall',[[.001,1.255],[.21,1.255],[.226,1.258],[.236,1.27],[.239,1.284],[.243,1.438],[.242,1.458],[.235,1.472],[.222,1.477],[.001,1.477]],metal,112);
turned(flask,'Grip / fluted Bakelite',[[.236,1.286],[.243,1.293],[.247,1.299],[.247,1.316],[.247,1.348],[.246,1.358],[.242,1.365],[.239,1.367]],dark,320,40);
torus(flask,'Grip edging / low',.242,.0033,1.29,polished);
torus(flask,'Grip edging / high',.242,.003,1.366,polished);
torus(flask,'Lip / rolled top',.227,.0055,1.471,polished);
turned(flask,'Crown stamped inset',[[.001,1.476],[.169,1.476],[.184,1.478],[.183,1.481],[.176,1.483],[.001,1.483]],metal);
for(const y of [.37,.97]) {
  rounded(flask,'Strap attachment block',[-.296,y,-.044],[.073,.118,.124],.021,green);
  const pin=mesh(flask,'Slotted steel pivot',new THREE.CylinderGeometry(.029,.029,.011,28),polished);
  pin.position.set(-.336,y,-.044);pin.rotation.z=Math.PI/2;
}
// Subtly flattened formed handle, leaving a real air gap against the barrel.
const strap=tube(flask,'Molded carry handle',[[-.31,.98,-.044],[-.39,.979,-.044],[-.447,.924,-.044],[-.456,.84,-.044],[-.456,.51,-.044],[-.444,.423,-.044],[-.392,.369,-.044],[-.312,.367,-.044]],.036,dark,68,14);
strap.scale.z=1.24;

turned(cup,'Wheel thrown exterior',[[.001,.041],[.20,.041],[.218,.05],[.231,.064],[.245,.088],[.263,.13],[.285,.222],[.301,.359],[.31,.444],[.308,.471],[.306,.478]],cupWall,112);
turned(cup,'Continuous glazed rim & inner wall',[[.306,.475],[.308,.485],[.307,.491],[.303,.497],[.297,.499],[.291,.497],[.286,.491],[.284,.483],[.284,.463],[.275,.357],[.258,.218],[.236,.133],[.214,.094],[.194,.082],[.16,.078],[.001,.078]],cupInner,112);
turned(cup,'Recessed biscuit foot',[[.001,.043],[.157,.043],[.163,.04],[.168,.026],[.173,.022],[.203,.022],[.21,.026],[.215,.039],[.214,.056],[.211,.062]],clay,96);
const cupHandle=tube(cup,'Hand-finished loop handle',[[.275,.388,0],[.336,.411,.002],[.422,.421,.004],[.484,.393,.003],[.503,.343,.002],[.501,.283,.001],[.478,.215,0],[.43,.164,0],[.359,.146,-.001],[.289,.154,0],[.263,.172,0]],.038,handleClay,76,18);
cupHandle.scale.z=1.09;
ellipsoid(cup,'Upper thumb join',[.288,.387,0],[.047,.048,.05],handleClay);
ellipsoid(cup,'Lower thumb join',[.272,.17,0],[.046,.05,.047],handleClay);
// Opaque liquid surface is intentional for broad AE renderer compatibility.
turned(cup,'Brew surface',[[.001,.419],[.277,.419],[.282,.421],[.282,.429],[.279,.429],[.275,.425],[.263,.424],[.001,.424]],infusion,112);
torus(cup,'Curved liquid meniscus',.279,.0025,.427,meniscus);
// A few tiny bubbles in a single peripheral group leave the center undisturbed.
for(let i=0;i<9;i++){
 const a=.55+random()*.24,r=.245+random()*.022,s=.002+random()*.0046;
 ellipsoid(cup,'Surface bubble',[Math.sin(a)*r,.425,Math.cos(a)*r],[s,s*.36,s],meniscus);
}
// String visibly traverses the rim and supports the clipped-corner tea tag.
tube(sachet,'Cotton / over the rim',[[.043,.426,.083],[.059,.429,.148],[.081,.464,.234],[.083,.492,.281],[.082,.501,.288],[.084,.5,.296],[.09,.483,.304],[.097,.437,.312],[.102,.391,.315],[.114,.348,.321]],.0031,thread,58,8);
const tag=group(sachet,'Ticket / folded stock');tag.position.set(.12,.264,.343);tag.rotation.set(-.09,.25,-.12);
const tagWidth=.136,tagHeight=.162;
const verts=[[-.5,-.5],[.5,-.5],[.5,.33],[.33,.5],[-.33,.5],[-.5,.33]];
const tagGeometry = new THREE.BufferGeometry();
tagGeometry.setAttribute('position',new THREE.Float32BufferAttribute(verts.flatMap(([x,y])=>[x*tagWidth,y*tagHeight,0]),3));
tagGeometry.setAttribute('uv',new THREE.Float32BufferAttribute(verts.flatMap(([x,y])=>[x+.5,y+.5]),2));
tagGeometry.setIndex([0,1,2,0,2,3,0,3,4,0,4,5]);tagGeometry.computeVertexNormals();
mesh(tag,'Vermilion tea ticket',tagGeometry,paper);
rounded(tag,'Staple',[0,.067,.0015],[.028,.0032,.003],.001,gold);

const targetDir=process.argv[2] ? resolve(process.argv[2]) : fileURLToPath(new URL('../Models',import.meta.url));
await mkdir(targetDir,{recursive:true});
const boundsInfo={};
for(const [name,prop] of [['Flask',flask],['Cup',cup]]){
 const partScene=new THREE.Scene();
 const pivot=new THREE.Group();
 partScene.add(pivot);pivot.add(prop);
 const initialBox=new THREE.Box3().setFromObject(pivot,true);
 pivot.position.sub(initialBox.getCenter(new THREE.Vector3()));
 partScene.updateMatrixWorld(true);
 const glb=await new GLTFExporter().parseAsync(partScene,{binary:true,onlyVisible:true});
 const validation=await validateBytes(new Uint8Array(glb));
 if(validation.issues.numErrors || validation.issues.numWarnings)throw Error(JSON.stringify(validation.issues));
 await writeFile(resolve(targetDir,name+'.glb'),Buffer.from(glb));
 const box=new THREE.Box3().setFromObject(partScene,true);
 boundsInfo[name]=box.getSize(new THREE.Vector3()).toArray();
}
await writeFile(resolve(targetDir,'bounds.json'),JSON.stringify(boundsInfo,null,2));
console.log(boundsInfo);
