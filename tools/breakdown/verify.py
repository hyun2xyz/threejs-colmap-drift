"""Integrity/layout checks; visual matchmove and actual playback remain separate."""
import argparse,hashlib,json,subprocess
from pathlib import Path
import cv2,numpy as np

p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args();d=a.output
v=d/'01_Water_Breakdown_Final_v7_1080x1350.mp4'
edl=json.loads((d/'edit-decision-list.json').read_text());boxes=json.loads((d/'layout-bounds.json').read_text())
probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(v)]));s=probe['streams'][0]
checks={'format':s['width']==1080 and s['height']==1350 and s['r_frame_rate']=='30/1' and abs(float(probe['format']['duration'])-16.5)<.001,
        '495_frame_edl':len(edl)==495 and [r['output_frame'] for r in edl]==list(range(495)),
        'rectangular_static_21px_captions':all(b['shape']=='sharp white rectangle' and b['font_size']==21 and b['rect'][3]==24 and not b['floating'] for row in boxes.values() for b in row),
        'approved_footer_text':all([b['text'] for b in row if b['role']=='footer']==['Only an LLM + Using My Custom Skills (Colmap + OpenGL, etc.)','See Caption for Details!'] for row in boxes.values()),
        'zero_glyph_motion':all(not any(x for line in r['footer_glyph_y_offsets'] for x in line) for r in edl),
        'combined_tracking_three_seconds':all(r.get('combined_visible') and r['wipe_progress']==0 for r in edl[90:180]),
        'direct_cloud_to_particles':edl[240]['views']==['pointcloud','particles'],
        'six_RTL_wipes':all([r.get('wipe_edge_x') for r in edl[start+1:start+8]]==[945,810,675,540,405,270,135] for start in [180,240,264,288,312,336]),
        'same_time_process_wipes':all(len(set(r.get('wipe_source_frames',[])))<=1 for r in edl[264:336]),
        'reset_to_first_frame':all(r['wipe_source_frames'][1]==0 for r in edl[336:345]),
        'one_second_hold':all(r['source_frame']==0 and r['held'] for r in edl[345:375]),
        'full_result_replay':[r['source_frame'] for r in edl[375:]]==[i*24//30 for i in range(120)]}
safe=True;spacing=True;margins=True
for stage,row in boxes.items():
    for b in row:
        x,y,w,h=b['rect'];safe &= x>=0 and y>=0 and x+w<=1080 and y+h<=1350
    for role in ['step','footer']:
        group=[b for b in row if b['role']==role]
        spacing &= all(q['rect'][1]-p['rect'][1]==27 for p,q in zip(group,group[1:]))
    footer=[b for b in row if b['role']=='footer'];bottom=1296 if stage=='comparison' else 979
    margins &= all(1080-b['rect'][0]-b['rect'][2]==24 for b in footer) and bottom-footer[-1]['rect'][1]-footer[-1]['rect'][3]==24
checks.update(caption_bounds=safe,uniform_27px_leading=spacing,equal_24px_footer_margins=margins)
cap=cv2.VideoCapture(str(v));count=0;blank=[];white=[];hold=[];reference=None
while True:
    ok,frame=cap.read()
    if not ok:break
    if count>=len(edl):raise ValueError('Video contains more frames than EDL')
    pic=frame[55:663] if edl[count]['stage']=='comparison' else frame[371:979]
    if pic.mean()<10 or pic.std()<10:blank.append(count)
    edge=edl[count].get('wipe_edge_x')
    if edge is not None:white.append(float(frame[650:800,edge-1:edge+1].mean()))
    if 345<=count<375:
        if reference is None:reference=frame.copy()
        hold.append(float(cv2.absdiff(frame,reference).mean()))
    count+=1
cap.release();checks.update(full_decode=count==495,no_blank_picture=not blank,white_separator=min(white)>235,static_result_hold=max(hold)<.5)
r=dict(passed=all(checks.values()),checks=checks,decoded_frames=count,sha256=hashlib.sha256(v.read_bytes()).hexdigest(),
       visual_review='Required separately: inspect actual points/grid, geometry, lighting, all transitions, and playback. These automated checks do not certify matchmove quality.')
(d/'integrity-report.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
raise SystemExit(0 if r['passed'] else 2)
