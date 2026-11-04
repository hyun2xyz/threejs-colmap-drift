# Water pass

`bake-water.mjs` seeds 370 particles and integrates five substeps per output frame. Pairwise pressure, attraction and viscosity are symmetric. Gravity is zero. An art-directed shear field deforms the main droplet. The constants are tuned for this shot.

`water.mjs` turns cached particle samples into a 56³ scalar field and extracts an isosurface using the Three.js r180 MarchingCubes addon. A browser can import `createWater(THREE, MarchingCubes)`, add its returned `object` to a scene, then call `update(seconds)`. Serve the module and generated `water-particles.bin` over HTTP. The optional MeshPhysicalMaterial uses an IOR of 1.333.

The delivered movie uses a separate renderer. `Source/water_surface.mjs` exports triangle positions and normals, and `Source/render_water_opengl.py` executes the shaders in [shaders](shaders/). The first pass records back-face positions and normals. The second samples the moving plate along an estimated refracted ray and the equirectangular HDRI along the reflected ray. Thin overlapping parts and offscreen refractions are approximations. The resulting RGBA movie uses straight alpha and carries the refracted background inside its silhouette.

The browser material and the native renderer share the particle cache and surface geometry. Edit the native shader for changes to the movie's optics. [Three.js notice](THREE-LICENSE.txt)
