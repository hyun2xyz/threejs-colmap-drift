#version 330
in vec3 p,n; layout(location=0) out vec4 pos;layout(location=1) out vec4 norm;
void main(){pos=vec4(p,1);norm=vec4(normalize(n),1);}
