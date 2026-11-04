/* Switch the object-pass environment light to a still or the first frame of a panorama video. */
(function () {
    if (!app.project) { alert("Open the generated Drift project first."); return; }
    var comp = null, env = null;
    for (var i = 1; i <= app.project.numItems; i++) {
        var item = app.project.item(i);
        if (item instanceof CompItem && item.name === "04  OBJECTS - HDRI and motion") {
            if (comp) { alert("Multiple object comps share this name. Give the target a unique name first."); return; }
            comp = item;
        }
    }
    if (!comp) { alert("Open the generated Drift project first."); return; }
    for (var n = 1; n <= comp.numLayers; n++) {
        var l = comp.layer(n);
        if (l instanceof LightLayer && l.lightType === LightType.ENVIRONMENT) {
            if (env) { alert("The object comp has multiple environment lights."); return; }
            env = l;
        }
    }
    if (!env) { alert("The object-pass environment light is missing."); return; }
    var file = File.openDialog("Choose a 360 panorama video or HDR / EXR still");
    if (!file) return;
    app.beginUndoGroup("Use first HDRI frame");
    var media = null, source = null, original = env.lightSource;
    try {
        media = app.project.importFile(new ImportOptions(file));
        if (!media.hasVideo) throw Error("The selected file has no picture.");
        source = comp.layers.add(media);
        if (!media.mainSource.isStill) {
            source.timeRemapEnabled = true;
            source.timeRemap.expression = "0";
        }
        source.startTime = 0;
        source.inPoint = 0;
        source.outPoint = comp.duration;
        source.name = "IBL SOURCE - first frame - " + media.name;
        source.enabled = false;
        env.lightSource = source;
        if (!env.lightSource || env.lightSource.index !== source.index) throw Error("New environment assignment failed.");
    } catch (err) {
        if (original) env.lightSource = original;
        if (source) source.remove();
        if (media) media.remove();
        alert(err.toString());
    } finally { app.endUndoGroup(); }
}());
