(() => {
 const listeners = new WeakMap();
 const fire=(o,n,arg)=> (listeners.get(o)?.[n] || []).forEach(f=>f(arg));
 class LatLng { constructor(a,b){this.a=a;this.b=b} getLat(){return this.a} getLng(){return this.b} }
 class Overlay {setMap(){} }
 class MapFixture {
  constructor(el,o){this.el=el;this.center=o.center;this.level=o.level;
   el.style.background='repeating-linear-gradient(0deg,#e7edf2 0 59px,#dce5ed 60px 61px)';
   const note=document.createElement('div');note.textContent='로컬 지도 대역 · 실제 지도 정합 검수 아님';note.style='position:absolute;top:45%;left:5%;color:#64748b;font-size:12px';el.append(note);
   el.addEventListener('click',()=>fire(this,'click',{latLng:new LatLng(35.8714,128.6014)}));
  }
  addControl(){} removeControl(){} setBounds(){} panBy(){} setCenter(p){this.center=p} panTo(p){this.center=p} getCenter(){return this.center} getLevel(){return this.level} setLevel(l){this.level=l}
  getProjection(){return {containerPointFromCoords:p=>({x:this.el.clientWidth/2+(p.getLng()-128.6014)*1000,y:this.el.clientHeight/2-(p.getLat()-35.8714)*1000})}}
 }
 class Search { keywordSearch(q,cb){cb([{x:'128.6014',y:'35.8714',place_name:'동인청사 인근 검수 기준점',address_name:'대구광역시 중구 동인동'}],'OK')} addressSearch(q,cb){cb([],'ZERO_RESULT')} }
 const maps={ load:cb=>cb(), Map:MapFixture, LatLng, LatLngBounds:class{extend(){}}, ZoomControl:class{},ControlPosition:{RIGHT:'right'},Size:class{},Point:class{},MarkerImage:class{},Marker:Overlay,Polygon:Overlay,CustomOverlay:Overlay,Circle:Overlay,Polyline:Overlay,MarkerClusterer:class{clear(){} addMarkers(){}},services:{Status:{OK:'OK',ZERO_RESULT:'ZERO_RESULT'},Places:Search,Geocoder:Search},
 event:{addListener(o,n,f){const list=listeners.get(o)||{};(list[n]??=[]).push(f);listeners.set(o,list)},removeListener(o,n,f){const list=listeners.get(o);if(list)list[n]=(list[n]||[]).filter(x=>x!==f)},trigger:fire}};
 window.kakao={maps};
 document.addEventListener('DOMContentLoaded',()=>{const note=document.createElement('div');note.textContent='로컬 검수 · 가짜 SDK / 고정 조회 자료 · 실기기 아님';note.style='position:fixed;bottom:0;right:0;z-index:9999;background:#fff3d6;color:#624510;font-size:10px;padding:2px 6px;pointer-events:none';document.body.append(note)});
})();
