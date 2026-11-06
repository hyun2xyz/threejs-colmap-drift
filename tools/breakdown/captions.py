"""Fixed, sharp rectangular captions for the portrait breakdown reference."""
import math
from PIL import Image, ImageDraw, ImageFont

class RectLine:
    def __init__(self, text, font_path, size=21):
        self.text=text;self.size=size;self.ss=4
        self.font=ImageFont.truetype(font_path,size*self.ss)
        measure=ImageDraw.Draw(Image.new('L',(1,1)))
        self.width=math.ceil(measure.textlength(text,font=self.font)/self.ss)+6
        self.height=24;self.cache={}

    def render(self,time=0.,floating=False,color=(0,0,0)):
        if floating:raise ValueError('Breakdown captions must remain stationary')
        color=tuple(color)
        if color not in self.cache:
            foreground=Image.new('RGBA',(self.width*self.ss,self.height*self.ss))
            ImageDraw.Draw(foreground).text((3*self.ss,18*self.ss),self.text,font=self.font,anchor='ls',fill=(*color,255))
            foreground=foreground.resize((self.width,self.height),Image.Resampling.LANCZOS)
            background=Image.new('RGBA',(self.width,self.height),(255,255,255,255))
            self.cache[color]=(background,foreground,[0.]*sum(not c.isspace() for c in self.text))
        return self.cache[color]

    def metadata(self):
        return dict(text=self.text,font_size=self.size,shape='sharp white rectangle',glyph_count=sum(not c.isspace() for c in self.text),
                    size=[self.width,self.height],baseline_offset=18,floating_amplitude_bound=0)
