(function(){
  // Lightweight UMD-compatible loader: if OrbitControls is not available
  // try to attach it by injecting a module script that imports the local
  // `OrbitControls.module.js`. This keeps a single code path that works
  // offline when /static/js/three.module.js and OrbitControls.module.js
  // are present.
  try{
    if(typeof window === 'undefined') return;
    if(window.OrbitControls) return;
    if(window.THREE && window.THREE.OrbitControls){ window.OrbitControls = window.THREE.OrbitControls; return; }
    // Insert a module script that imports the module-based OrbitControls by src (simpler, avoids string-encoding issues)
    var s = document.createElement('script');
    s.type = 'module';
    s.src = '/static/js/OrbitControls.module.js';
    // After module loads, try to expose the exported OrbitControls on window
    s.onload = function(){
      try{
        if(window.OrbitControls) return;
        if(window.THREE && window.THREE.OrbitControls){ window.OrbitControls = window.THREE.OrbitControls; }
      }catch(_){ }
    };
    s.onerror = function(){};
    document.head.appendChild(s);
  }catch(e){ /* ignore */ }
})();
