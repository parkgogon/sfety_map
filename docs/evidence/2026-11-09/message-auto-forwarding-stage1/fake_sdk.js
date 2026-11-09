// UI automation fixture only: no real Kakao SDK, map tiles, or upstream requests.
(() => {
  class LatLng {constructor(lat,lng){this.lat=lat;this.lng=lng;}getLat(){return this.lat;}getLng(){return this.lng;}}
  class Bounds {constructor(){this.points=[];}extend(p){this.points.push(p);}}
  class FixtureMap {
    constructor(element){this.element=element;this.items=[];this.listeners={};this.bounds=null;this.element.style.position='relative';
      this.element.style.backgroundImage='linear-gradient(#dce7ed 1px, transparent 1px),linear-gradient(90deg,#dce7ed 1px,transparent 1px)';
      this.element.style.backgroundSize='36px 36px';
      const label=document.createElement('small');label.textContent='로컬 테스트 지도 · 실제 지도 타일 미사용';label.style.cssText='position:absolute;left:8px;top:8px;background:white;padding:5px;z-index:20';element.append(label);
      element.addEventListener('click',event=>{const rect=element.getBoundingClientRect();const b=this.bounds;
        const lat=b?b.maxLat-(event.clientY-rect.top)/rect.height*(b.maxLat-b.minLat):35.85;
        const lng=b?b.minLng+(event.clientX-rect.left)/rect.width*(b.maxLng-b.minLng):128.5;
        (this.listeners.click||[]).forEach(handler=>handler({latLng:new LatLng(lat,lng)}));});
    }
    addControl(){}removeControl(){}relayout(){this.render();}
    setBounds(bounds){this.bounds={minLat:Math.min(...bounds.points.map(p=>p.lat)),maxLat:Math.max(...bounds.points.map(p=>p.lat)),minLng:Math.min(...bounds.points.map(p=>p.lng)),maxLng:Math.max(...bounds.points.map(p=>p.lng))};this.render();}
    render(){const b=this.bounds;this.items.forEach(item=>{if(!b)return;const p=item.options.position||item.options.center;
      item.node.style.left=((p.lng-b.minLng)/(b.maxLng-b.minLng)*100)+'%';item.node.style.top=((b.maxLat-p.lat)/(b.maxLat-b.minLat)*100)+'%';
      if(item.options.radius){const width=item.options.radius/111000/(b.maxLat-b.minLat)*this.element.clientHeight*2;item.node.style.width=width+'px';item.node.style.height=width+'px';}
    });}
  }
  class Overlay {
    constructor(options){this.options=options;this.node=document.createElement('div');this.node.style.cssText='position:absolute;transform:translate(-50%,-100%);z-index:'+(options.zIndex||1);if(options.content)this.node.append(options.content);this.setMap(options.map);}
    setMap(map){if(this.map){this.map.items=this.map.items.filter(i=>i!==this);this.node.remove();}this.map=map;if(map){map.items.push(this);map.element.append(this.node);map.render();}}
  }
  class Circle extends Overlay {constructor(options){super(options);this.node.style.cssText+='border:2px solid #176b87;border-radius:50%;transform:translate(-50%,-50%);pointer-events:none;background:#86bed015';this.map?.render();}}
  window.kakao={maps:{load:callback=>callback(),Map:FixtureMap,LatLng,LatLngBounds:Bounds,ZoomControl:class{},ControlPosition:{RIGHT:1},CustomOverlay:Overlay,Circle,
    event:{addListener:(target,name,handler)=>{target.listeners[name]??=[];target.listeners[name].push(handler);},removeListener:(target,name,handler)=>{target.listeners[name]=(target.listeners[name]||[]).filter(h=>h!==handler);},trigger:(target,name)=>{(target.listeners[name]||[]).forEach(h=>h());}}}};
})();
