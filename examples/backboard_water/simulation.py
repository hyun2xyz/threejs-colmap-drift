"""Reduced-order bead motion on the measured plane. Coordinates and speeds use metres."""
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np

GRID = 768
BOARD_W = 1.8
BOARD_H = 1.2
HEIGHT = 512
SCALE = GRID / BOARD_W
DT = 1 / 24 / 6

def configure(aspect=1.5, grid=768, fps=24):
    global GRID, BOARD_H, HEIGHT, SCALE, DT
    if aspect <= 0 or grid < 128 or fps <= 0:
        raise ValueError("Positive aspect/fps and grid>=128 required")
    GRID = int(grid)
    BOARD_H = BOARD_W / aspect
    HEIGHT = round(GRID * BOARD_H / BOARD_W)
    SCALE = GRID / BOARD_W
    DT = 1 / float(fps) / 6


class Runoff:
    def __init__(self):
        self.rng = np.random.default_rng(31415)
        self.drops = []
        self.trail = np.zeros((HEIGHT, GRID), np.float32)
        self.added = self.runout = self.deposited = self.distance = 0.
        self.merges = 0
        self.jets = [1.22, 1.33, 1.43, 1.54, 1.65]
        self.next = np.array([.025, .26, .74, .40, .16])
        self.t = 0.
        for _ in range(230):
            self.spawn(self.rng.uniform(1.13, 1.755), self.rng.uniform(.03, BOARD_H-.06),
                       self.rng.uniform(.0015, .0038))
        # A wet board at the start of the shot, with a few moving heads already visible.
        for x in self.jets:
            self.spawn(x, self.rng.uniform(.12, .8), self.rng.uniform(.0045, .0065))

    def spawn(self, x, y, radius):
        # Radius-cubed is a volume proxy. Coalescence adds volumes, not radii.
        volume = radius**3
        self.added += volume
        self.drops.append([x, y, volume, 0., 0.])

    def tick(self):
        for j, x in enumerate(self.jets):
            if self.t >= self.next[j]:
                self.spawn(x + self.rng.normal(0, .003), .055,
                           self.rng.uniform(.0035, .0055))
                self.next[j] += self.rng.uniform(.65, 1.65)
        if self.rng.random() < 9 * DT:
            self.spawn(self.rng.uniform(1.13, 1.755), self.rng.uniform(.03, BOARD_H-.06),
                       self.rng.uniform(.0016, .0036))
        self.trail *= math.exp(-DT/7.8)
        live = []
        for x, y, vol, vx, vy in self.drops:
            radius = vol**(1/3)
            px, py = round(x*SCALE), round(y*SCALE)
            adhesion = .0032 * (1+.16*math.sin(83*x+47*y)*math.cos(24*y))
            wet = min(.75, self.trail[np.clip(py,0,HEIGHT-1), np.clip(px,0,GRID-1)] / .3)
            mobile = max(0., 1.-(adhesion*(1.-.45*wet)/radius)**2)
            # Effective gravity opposed by contact-angle hysteresis and drag.
            vy = max(0., vy + DT*(1.1*mobile - (6. + 7*(1-mobile))*vy))
            roughness = .60*math.sin(21*x+19*y)+.35*math.cos(82*y-32*x)
            vx += DT*(.12*roughness*mobile - 9.*vx)
            nx = np.clip(x+vx*DT, .022, BOARD_W-.022)
            ny = y+vy*DT
            length = math.hypot(nx-x,ny-y)
            self.distance += length
            if length > .00003:
                lost = vol*(1.-math.exp(-.62*length))
                vol -= lost
                self.deposited += lost
                thick = max(1, round(radius*SCALE*.60))
                # The refreshed film thins by drainage; units of the surface cache are mm.
                layer = min(.25, .045+radius*22.)
                cv2.line(self.trail,(px,py),(round(nx*SCALE),round(ny*SCALE)),
                         float(max(layer,self.trail[min(max(py,0),HEIGHT-1),min(max(px,0),GRID-1)])),
                         thick,cv2.LINE_8)
            if ny < BOARD_H-.014:
                live.append([nx,ny,vol,vx,vy])
            else:
                self.runout += vol
        self.drops = []
        cells = {}
        for d in sorted(live,key=lambda v:-v[2]):
            cell = (int(d[0]/.018),int(d[1]/.018))
            hit = None
            for xx in range(cell[0]-1,cell[0]+2):
                for yy in range(cell[1]-1,cell[1]+2):
                    for b in cells.get((xx,yy),()):
                        if math.hypot(d[0]-b[0],d[1]-b[1]) < .82*(d[2]**(1/3)+b[2]**(1/3)):
                            hit=b
                            break
                    if hit is not None: break
                if hit is not None: break
            if hit is None:
                cells.setdefault(cell,[]).append(d)
                self.drops.append(d)
            else:
                total = hit[2]+d[2]
                for k in (0,1,3,4):
                    hit[k] = (hit[k]*hit[2]+d[k]*d[2])/total
                hit[2] = total
                self.merges += 1
        self.t += DT

    def surface(self):
        image = cv2.GaussianBlur(self.trail,(0,0),.85)
        for x,y,vol,vx,vy in self.drops:
            radius = vol**(1/3)
            rx = radius*SCALE
            ry = rx*(1.+vy*2.5)
            cx,cy = x*SCALE,y*SCALE
            i0,i1 = max(0,math.floor(cx-rx)),min(GRID,math.ceil(cx+rx+1))
            j0,j1 = max(0,math.floor(cy-ry)),min(HEIGHT,math.ceil(cy+ry+1))
            yy,xx = np.ogrid[j0:j1,i0:i1]
            r2 = ((xx-cx)/rx)**2+((yy-cy)/ry)**2
            cap = np.maximum(1.-r2,0.)**.78 * (radius*240.)
            dst=image[j0:j1,i0:i1]
            np.maximum(dst,cap,out=dst)
        return np.uint16(np.clip(np.rint(image*1000.),0,65535))
