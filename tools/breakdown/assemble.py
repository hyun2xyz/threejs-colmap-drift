"""Assemble the v6 live-action breakdown from actual shot-specific passes."""
import argparse, hashlib, json, subprocess
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageFont
from captions import RectLine
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser()
p.add_argument('--manifest',required=True,type=Path)
p.add_argument('--output',required=True,type=Path)
p.add_argument('--spec',type=Path,default=ROOT/'docs/breakdown/spec.json')
p.add_argument('--font',type=Path)
p.add_argument('--stills',nargs='*',type=float)
a=p.parse_args();OUT=a.output.resolve();OUT.mkdir(parents=True,exist_ok=True)
S=json.loads(a.spec.read_text());N=495
if S['version']!=6 or S['size']!=[1080,1350] or S['fps']!=[30,1]:raise ValueError('This reference assembler implements the v6 1080x1350/30fps specification')
fonts=[a.font] if a.font else [Path('/System/Library/Fonts/Helvetica.ttc'),Path('C:/Windows/Fonts/arial.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
font_path=next((p for p in fonts if p and p.is_file()),None)
if font_path is None:raise ValueError('Supply --font with a valid Helvetica or Arial font file')
S['labels']['font']=str(font_path)
manifest=json.loads(a.manifest.read_text())
if [manifest['width'],manifest['height'],manifest['frames'],manifest['fps']]!=[1280,720,96,[24,1]]:raise ValueError('Expected synchronized 1280x720 / 96-frame / 24fps inputs')
for name in ['cache','stills']:(OUT/name).mkdir(exist_ok=True)
frames={};expected=96*1280*720*3
for name in ['original','result','tracking_ground','pointcloud','particles','wireframe','refraction']:
    source=Path(manifest['passes'][name]);source=source if source.is_absolute() else a.manifest.resolve().parent/source
    if not source.is_file():raise FileNotFoundError(source)
    raw=source if source.suffix=='.rgb' else OUT/'cache'/f'{name}.rgb'
    if source.suffix!='.rgb':
        cache_meta=raw.with_suffix('.json')
        with source.open('rb') as handle:source_sha=hashlib.file_digest(handle,'sha256').hexdigest()
        identity=dict(source=str(source.resolve()),sha256=source_sha)
        if raw.exists() and (not cache_meta.exists() or json.loads(cache_meta.read_text())!=identity):
            raise ValueError(f'Cached input changed or has no provenance; use a new output folder: {source}')
    if source.suffix!='.rgb' and not raw.exists():
        probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_streams','-of','json',str(source)]))['streams'][0]
        if (probe['width'],probe['height'])!=(1280,720) or probe['r_frame_rate']!='24/1':raise ValueError(f'Wrong pass size/fps: {source}')
        temp=raw.with_suffix('.part')
        subprocess.run(['ffmpeg','-v','error','-n','-i',str(source),'-f','rawvideo','-pix_fmt','rgb24','-threads','2',str(temp)],check=True)
        if temp.stat().st_size!=expected:raise ValueError(f'Wrong pass length: {source}')
        temp.rename(raw)
        cache_meta.write_text(json.dumps(identity,indent=2)+'\n')
    if raw.stat().st_size!=expected:raise ValueError(f'Wrong raw RGB size: {raw}')
    frames[name]=np.memmap(raw,dtype='u1',mode='r',shape=(96,720,1280,3))
def sample(name,index):return cv2.resize(frames[name][min(95,max(0,index))],(1080,608),interpolation=cv2.INTER_AREA)
font_size=21;font=ImageFont.truetype(S['labels']['font'],font_size)

line_objects={}
def line(text):
    if text not in line_objects:line_objects[text]=RectLine(text,S['labels']['font'],21)
    return line_objects[text]

def place(background,foreground,text,x,y,role,color=(0,0,0),right=False,time=0.,floating=False):
    obj=line(text)
    if right:x-=obj.width
    bg,fg,offsets=obj.render(time,floating,color)
    background.alpha_composite(bg,(x,y));foreground.alpha_composite(fg,(x,y))
    return dict(**obj.metadata(),role=role,rect=[x,y,obj.width,obj.height],floating=floating),offsets

def static_labels(stage):
    bg=Image.new('RGBA',(1080,1350));fg=Image.new('RGBA',(1080,1350));bounds=[]
    if stage=='comparison':
        for text,y in [('RESULT',79),('ORIGINAL',712)]:bounds.append(place(bg,fg,text,24,y,'title')[0])
    else:
        result=stage.startswith('result');bounds.append(place(bg,fg,'RESULT' if result else 'Process',24,395,'title')[0])
        if not result:
            idx=S['merged_process_stages'][stage]
            for k in range(idx+1):bounds.append(place(bg,fg,S['step_labels'][k],40,422+27*k,'step',(0,0,0) if k==idx else (125,128,126))[0])
    bg.alpha_composite(fg)
    return np.array(bg),bounds

def footer(stage,time):
    bottom=1296 if stage=='comparison' else 979
    texts=S['footer']['lines'];objs=[line(text) for text in texts]
    y=bottom-24-objs[1].height-27
    left=min(1056-obj.width for obj in objs)
    height=max(objs[0].height,27+objs[1].height)
    bg=Image.new('RGBA',(1056-left,height));fg=Image.new('RGBA',bg.size)
    bounds=[];offsets=[]
    for k,(text,obj) in enumerate(zip(texts,objs)):
        b,o=place(bg,fg,text,1056-left,27*k,'footer',right=True,time=time,floating=False)
        b['rect'][0]+=left;b['rect'][1]+=y;bounds.append(b);offsets.append(o)
    bg.alpha_composite(fg)
    return np.array(bg),(left,y),bounds,offsets

overlays={};bounds={};footers={}
for row in S['timeline']:
    stage=row['stage'];overlays[stage],bounds[stage]=static_labels(stage)
    footers[stage]=footer(stage,0);bounds[stage]+=footers[stage][2]

def wipe(old,new,u):
    if u<=0:return old,None
    if u>=1:return new,None
    edge=(1-u)*1080
    mask=np.clip((np.arange(1080)-edge+1)/2,0,1)[None,:,None]
    result=np.uint8(old*(1-mask)+new*mask)
    x=round(edge);result[:,max(0,x-1):min(1080,x+1)]=255
    return result,x

def frame_at(i):
    t=i/30;stage=next(r['stage'] for r in S['timeline'] if r['start']<=t<r['end'])
    canvas=np.full((1350,1080,3),[252,254,253],np.uint8)
    rec=dict(output_frame=i,time=t,stage=stage);edge=None
    if stage=='comparison':
        source=i*24//30;canvas[55:663]=sample('result',source);canvas[688:1296]=sample('original',source);rec['views']=['result','original']
    elif stage=='camera':
        relative=i-90;source=min(94,1+relative*24//30)
        point_frame=max(0,(relative-90)*24//30)
        u=(relative-90)/8
        pic,edge=wipe(sample('tracking_ground',source),sample('pointcloud',point_frame),u)
        rec.update(views=['tracking_ground','pointcloud'],combined_source_frame=source,pointcloud_source_frame=point_frame,wipe_progress=min(1,max(0,u)),combined_visible=u<1)
        if u>=1:source=point_frame
        canvas[371:979]=pic
    elif 240<=i<336:
        relative=i-240;source=relative*24//30;k=min(3,relative//24)
        old,new=[('pointcloud','particles'),('particles','wireframe'),('wireframe','refraction'),('refraction','result')][k]
        u=min(1,(relative-k*24)/8);old_source=min(95,48+relative*24//30) if k==0 else source
        pic,edge=wipe(sample(old,old_source),sample(new,source),u)
        rec.update(views=[old,new],wipe_progress=u,wipe_source_frames=[old_source,source],continuous_clock_frame=relative)
        canvas[371:979]=pic
    elif stage=='result_wipe':
        source=0;outgoing=(i-240)*24//30;u=(i-336)/8
        pic,edge=wipe(sample('result',outgoing),sample('result',0),u)
        rec.update(views=['result','result_first_frame'],wipe_progress=u,wipe_source_frames=[outgoing,0],intentional_time_reset=True)
        canvas[371:979]=pic
    else:
        source=0 if stage=='result_hold' else (i-375)*24//30
        canvas[371:979]=sample('result',source);rec.update(views=['result'],held=stage=='result_hold')
    rec['source_frame']=source
    if edge is not None:rec.update(wipe_edge_x=edge,wipe_direction='right to left',wipe_edge_width=2)
    overlay=overlays[stage];alpha=overlay[:,:,3:4].astype('f4')/255
    canvas=np.uint8(np.clip(canvas*(1-alpha)+overlay[:,:,:3]*alpha,0,255))
    patch,(x,y),_,offsets=footers[stage]
    al=patch[:,:,3:4].astype('f4')/255;h,w=patch.shape[:2]
    canvas[y:y+h,x:x+w]=np.uint8(np.clip(canvas[y:y+h,x:x+w]*(1-al)+patch[:,:,:3]*al,0,255))
    rec['footer_glyph_y_offsets']=offsets
    return canvas,rec

def save(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(path)
if a.stills is not None:
    for sec in a.stills:
        i=round(sec*30);im,rec=frame_at(i);cv2.imwrite(str(OUT/'stills'/f'look_{i:04}.png'),im[:,:,::-1]);print(dict(frame=i,stage=rec['stage']))
else:
    out=OUT/'01_Water_Breakdown_Final_v6_1080x1350.mp4'
    if out.exists():raise RuntimeError('Preserving existing final movie')
    enc=subprocess.Popen(['ffmpeg','-v','error','-n','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1350','-r','30','-i','-','-an','-vf','scale=in_range=pc:out_range=tv:out_color_matrix=bt709','-c:v','libx264','-crf','17','-preset','medium','-threads','4','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-color_range','tv','-movflags','+faststart',str(out)],stdin=subprocess.PIPE)
    edl=[]
    for i in range(N):
        im,rec=frame_at(i);enc.stdin.write(np.ascontiguousarray(im).tobytes());edl.append(rec)
        if i%30==15 or i in [0,180,188,240,340,344,345,374,375,494]:cv2.imwrite(str(OUT/'stills'/f'frame_{i:04}.jpg'),im[:,:,::-1])
        if i%120==0:print(f'v6 {i}/{N}',flush=True)
    enc.stdin.close();assert enc.wait()==0
    save(OUT/'edit-decision-list.json',edl);save(OUT/'layout-bounds.json',bounds);save(OUT/'style.json',S)
    save(OUT/'state.json',dict(stage='rendered_needs_review',output=str(out),frames=N,size=[1080,1350],fps=[30,1],next='Verify actual combined tracking/grid, extended duration, direct pointcloud-to-SPH, rectangular stationary captions, equal leading and full playback'))
    print(out)
