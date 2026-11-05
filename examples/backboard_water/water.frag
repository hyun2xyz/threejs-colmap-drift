#version 330
uniform sampler2D plate, depthMicrons, frontHoldout, environment;
uniform mat3 screenToBoard;
uniform mat4 camera;
uniform float aspect, focal;
uniform vec4 crop;uniform vec2 outputSize;
uniform int frame;
layout(location=0) out vec4 finalPass;
layout(location=1) out vec4 previsPass;
layout(location=2) out vec4 materialPass;
layout(location=3) out vec4 lightingPass;

vec3 linearize(vec3 c) {return mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(vec3(.04045),c));}
vec3 encode(vec3 c) {c=max(c,0.);return mix(c*12.92,1.055*pow(c,vec3(1./2.4))-.055,step(vec3(.0031308),c));}
vec3 sampleLight(vec3 ray) {
    vec2 uv=vec2(atan(ray.x,ray.z)/6.2831853+.5,acos(clamp(ray.y,-1.,1.))/3.14159265);
    // Filter the source-view proxy to avoid a razor-sharp studio-like band.
    vec2 t=1./vec2(textureSize(environment,0));
    return .40*texture(environment,uv).rgb+.15*(texture(environment,uv+vec2(3,0)*t).rgb+
           texture(environment,uv-vec2(3,0)*t).rgb+texture(environment,uv+vec2(0,3)*t).rgb+
           texture(environment,uv-vec2(0,3)*t).rgb);
}
void main() {
    vec2 size=vec2(textureSize(plate,0));
    vec2 pixel=crop.xy+vec2(gl_FragCoord.x/outputSize.x,1.-gl_FragCoord.y/outputSize.y)*crop.zw,uv=pixel/size;
    vec3 h=screenToBoard*vec3(pixel-.5,1.);
    vec2 dims=vec2(textureSize(depthMicrons,0)),buv=(h.xy/h.z+.5)/dims;
    finalPass=previsPass=materialPass=lightingPass=vec4(0);
    if(any(lessThan(buv,vec2(0)))||any(greaterThan(buv,vec2(1))))return;
    float mm=texture(depthMicrons,buv).r;
    float a=smoothstep(.006,.085,mm)*(1.-texture(frontHoldout,uv).r);
    a*=smoothstep(.015,.028,buv.x)*smoothstep(.015,.028,1.-buv.x)*smoothstep(.02,.035,buv.y)*smoothstep(.02,.035,1.-buv.y);
    if(a<.001)return;
    vec2 d=1./dims;
    float sx=texture(depthMicrons,buv+vec2(d.x,0)).r-texture(depthMicrons,buv-vec2(d.x,0)).r;
    float sy=texture(depthMicrons,buv+vec2(0,d.y)).r-texture(depthMicrons,buv-vec2(0,d.y)).r;
    vec3 N=normalize(vec3(-sx,sy,2.*1800./dims.x));
    vec3 pt=vec3((buv.x-.5)*1.8,(.5-buv.y)*1.8/aspect,mm*.001);
    vec3 V=normalize(camera[3].xyz-pt);
    vec3 ray=refract(-V,N,1./1.333);
    vec2 dv=ray.xy/max(.17,-ray.z)+V.xy/max(.17,V.z);
    float pp=focal/max(.2,length(camera[3].xyz-pt));
    // Thin water on glass: no fictitious20mm film and no4.2x second image.
    // The source plate represents both glass and objects behind it. A short
    // effective background distance is a bounded screen-space approximation.
    vec2 shift=vec2(dv.x,-dv.y)*pp*(.028+.002*mm);
    float sl=length(shift);if(sl>3.2)shift*=3.2/sl;
    vec3 substrate=linearize(texture(plate,clamp(uv+shift/size,0.,1.)).rgb);
    // Clear water: preserve the original pane color, grime and scratches.
    // Weak near-neutral absorption over the actual cached millimetre thickness.
    substrate*=exp(-vec3(.003,.002,.0015)*mm);
    // The photographed pane is dusty. A small neutral wetting response replaces
    // the former strong blue dye; it is an artistic surface-match approximation.
    substrate*=mix(1.,.82,smoothstep(.025,.24,mm));
    vec3 R=reflect(-V,N);
    float F=.0204+.9796*pow(1.-max(0.,dot(N,V)),5.);
    vec3 env=sampleLight(R)*1.85;
    // Energy-conserving Fresnel blend; no extra22% edge reflection, painted
    // blue/white flank, shadow stripe, or independent glitter light.
    vec3 wet=mix(substrate,env,F);
    // Proxy direct daylight, aligned with the existing plate lighting direction.
    // GGX water-interface highlight: localized moving glints, not a painted rim.
    vec3 L=normalize(vec3(-.61,.73,.35));
    vec3 halfV=normalize(L+V);
    float NL=max(dot(N,L),0.),NV=max(dot(N,V),.001),NH=max(dot(N,halfV),0.);
    float VH=max(dot(V,halfV),0.),rough=.105,alpha=rough*rough,a2=alpha*alpha;
    float den=NH*NH*(a2-1.)+1.;
    float D=a2/(3.14159265*den*den);
    float k=(rough+1.)*(rough+1.)/8.;
    float G=(NL/(NL*(1.-k)+k))*(NV/(NV*(1.-k)+k));
    float FS=.0204+.9796*pow(1.-VH,5.);
    float spec=D*G*FS/(4.*max(NL,.001)*NV)*NL;
    wet+=vec3(1.,.97,.90)*min(spec*.9,1.8)*smoothstep(.10,.5,mm);

    vec3 lightDir=normalize(vec3(-.61,.73,.35));
    float clay=clamp(.62+.55*dot(N,lightDir),.19,1.);
    previsPass=vec4(vec3(clay),a);
    materialPass=vec4(encode(substrate),a);
    lightingPass=vec4(encode(wet),a);
    finalPass=lightingPass;
}
