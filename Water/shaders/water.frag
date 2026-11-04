#version 330
uniform sampler2D positions,normals,plate,hdr;uniform vec3 eye;uniform mat4 vp,crop;uniform vec2 dim;
in vec3 p,n;out vec4 col;
vec2 uv(mat4 mat,vec3 xyz){vec4 v=mat*vec4(xyz,1);return .5+.5*v.xy/v.w;}
vec3 sky(vec3 dir){dir=normalize(dir);vec2 q=vec2(atan(dir.z,dir.x)/6.283185+.5,asin(clamp(dir.y,-1.,1.))/3.141593+.5);return texture(hdr,q).rgb*.74;}
vec3 linearize(vec3 c){return mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(.04045,c));}
vec3 encode(vec3 c){return mix(12.92*c,1.055*pow(max(c,0.),vec3(1./2.4))-.055,step(.0031308,c));}
float fren(float c){return .02037+.97963*pow(1.-clamp(c,0.,1.),5.);}
void main(){
 vec3 I=normalize(p-eye), N=normalize(n);if(dot(I,N)>0.)N=-N;
 vec3 inside=refract(I,N,1./1.333), refl=sky(reflect(I,N));vec2 base=gl_FragCoord.xy/dim;
 vec4 exitPos=texture(positions,base);vec3 exitN=normalize(texture(normals,base).xyz);
 float thick=clamp(distance(exitPos.xyz,p),.002,1.40);
 vec2 est=uv(crop*vp,p+inside*thick);vec4 v=texture(positions,est);
 if(v.a>.9 && all(greaterThan(est,vec2(0.))) && all(lessThan(est,vec2(1.))) && distance(v.xyz,p)<1.6){exitPos=v;exitN=normalize(texture(normals,est).xyz);}
 vec3 exitRay=refract(inside,-exitN,1.333);float fres=fren(dot(-I,N));
 vec3 transmission;
 if(dot(exitRay,exitRay)<.001){transmission=sky(reflect(inside,-exitN));}
 else{
  vec2 q=uv(vp,exitPos.xyz+exitRay*1.8);
  float edge=min(min(q.x,1.-q.x),min(q.y,1.-q.y));
  vec3 transmitted=linearize(texture(plate,clamp(q,vec2(.002),vec2(.998))).rgb);
  transmission=mix(sky(exitRay),transmitted,smoothstep(0.,.035,edge));
 }
 vec3 tint=exp(-vec3(.087,.030,.017)*thick);
 vec3 lit=mix(transmission*tint,refl,fres);
 // A gentle shoulder retains texture in canopy reflections brighter than display white.
 lit=mix(lit,.78+(lit-.78)/(1.+max(lit-.78,0.)/.22),step(.78,lit));
 col=vec4(encode(max(vec3(0),lit)),1);
}
