#version 330
uniform mat4 model, vp, crop; in vec3 vertex, normal; out vec3 p,n;
void main(){ vec4 world=model*vec4(vertex,1);p=world.xyz;n=normalize(mat3(model)*normal);gl_Position=crop*vp*world; }
